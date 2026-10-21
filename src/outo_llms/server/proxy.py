"""Inference proxy: forwards requests to the active engine.

The primary surface is the Anthropic Messages API (``POST /v1/messages``).
The OpenAI endpoints (``POST /v1/chat/completions``, ``POST /v1/completions``)
are kept for compatibility; every bundled engine (llama.cpp, vLLM, SGLang)
serves both protocol families on 127.0.0.1. This router adds auth, model
resolution, and usage metering on top. ``EngineManager`` is imported lazily
inside handlers so registry-only CLI usage never pulls in the engines
machinery.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..engines.base import ModelRef
from . import accounts, live, registry, usage
from .deps import SessionOrWorkspaceDep, WorkspaceDep, api_error

router = APIRouter(prefix="/v1", tags=["proxy"])

_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=None)


@router.get("/models")
def list_models(ctx: SessionOrWorkspaceDep) -> dict[str, object]:
    """List registered models in the OpenAI ``GET /v1/models`` shape.

    Every inference client (OpenAI SDK, Anthropic SDK base-url probing,
    llama.cpp/vLLM/SGLang tooling) understands this shape, and every
    bundled engine serves it for its readiness probe.
    """
    return {
        "object": "list",
        "data": [
            {
                "id": m["name"],
                "object": "model",
                "created": 0,
                "owned_by": "outo-llms",
            }
            for m in registry.list_models()
        ],
    }


@router.get("/models/{name:path}")
def model_detail(name: str, ctx: SessionOrWorkspaceDep) -> dict[str, object]:
    """Registry detail for one model, used by the web UI's model page."""
    for row in registry.list_models():
        if row["name"] == name:
            return {
                "name": row["name"],
                "source": row["source"],
                "kind": row["kind"],
                "engine": row["engine"],
                "created_at": row["created_at"],
            }
    raise api_error(
        404, f"model {name!r} not found", code="model_not_found"
    )


def _resolve_model(body: dict[str, object]) -> tuple[str, ModelRef]:
    model_name = body.get("model")
    if not isinstance(model_name, str) or not model_name:
        raise api_error(400, "request body is missing 'model'")
    model_ref = registry.get_model(model_name)
    if model_ref is None:
        raise api_error(
            404,
            f"model {model_name!r} not found; add it with `outo-llms models add`",
            code="model_not_found",
        )
    return model_name, model_ref


def _ensure_base_url(model_ref: ModelRef) -> str:
    from outo_llms.engines.manager import EngineManager

    manager = EngineManager()
    if not manager.is_installed():
        raise api_error(
            502,
            f"engine {manager.current_name()!r} is not installed; "
            f"run `outo-llms engine install {manager.current_name()}`",
        )
    try:
        return manager.ensure_running(model_ref)
    except (RuntimeError, ValueError) as exc:
        raise api_error(502, str(exc)) from exc


def _usage_tokens(data: dict[str, Any], protocol: str) -> tuple[int, int] | None:
    """Extract (prompt, completion) tokens from a response body.

    Anthropic bodies carry ``usage.input_tokens``/``usage.output_tokens``;
    OpenAI bodies carry ``usage.prompt_tokens``/``usage.completion_tokens``.
    """
    usage_data = data.get("usage")
    if not isinstance(usage_data, dict):
        return None
    if protocol == "anthropic":
        return (
            int(usage_data.get("input_tokens") or 0),
            int(usage_data.get("output_tokens") or 0),
        )
    return (
        int(usage_data.get("prompt_tokens") or 0),
        int(usage_data.get("completion_tokens") or 0),
    )


def _record_nonstream_usage(
    ctx: accounts.WorkspaceContext, model: str, data: dict[str, Any], protocol: str
) -> None:
    tokens = _usage_tokens(data, protocol)
    if tokens is None:
        return
    prompt_tokens, completion_tokens = tokens
    usage.record_usage(
        ctx.workspace_id,
        model,
        prompt_tokens,
        completion_tokens,
        key_id=ctx.key_id,
    )


def _stream_usage(text: str, protocol: str) -> tuple[int, int] | None:
    """Scan a captured SSE stream for token counts, per protocol.

    Anthropic streams carry ``usage.input_tokens`` on ``message_start`` and
    the final ``usage.output_tokens`` on ``message_delta``. OpenAI streams
    carry a complete ``usage`` object on the final usage-bearing event
    (the proxy requests it via ``stream_options.include_usage``).
    """
    input_tokens = 0
    output_tokens = 0
    found = False
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :].strip()
        if payload == "[DONE]":
            continue
        obj = json.loads(payload)
        if not isinstance(obj, dict):
            continue
        if protocol == "anthropic":
            event_type = obj.get("type")
            if event_type == "message_start":
                message = obj.get("message")
                if isinstance(message, dict):
                    tokens = _usage_tokens(message, protocol)
                    if tokens is not None:
                        input_tokens = tokens[0]
                        found = True
            elif event_type == "message_delta":
                usage_data = obj.get("usage")
                if isinstance(usage_data, dict):
                    output_tokens = int(usage_data.get("output_tokens") or 0)
                    found = True
        elif obj.get("usage") is not None:
            tokens = _usage_tokens(obj, protocol)
            if tokens is not None:
                input_tokens, output_tokens = tokens
                found = True
    return (input_tokens, output_tokens) if found else None


async def _forward_nonstream(
    url: str,
    body: dict[str, object],
    ctx: accounts.WorkspaceContext,
    model: str,
    protocol: str,
) -> JSONResponse:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            upstream = await client.post(url, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise api_error(502, f"could not connect to engine: {exc}") from exc
    try:
        data = upstream.json()
    except ValueError as exc:
        raise api_error(502, "engine returned an invalid response") from exc
    
    # Validate Anthropic responses have the expected shape
    if protocol == "anthropic" and upstream.status_code == 200:
        if not isinstance(data, dict):
            raise api_error(
                502,
                f"engine returned non-object response: {type(data).__name__}"
            )
        # A valid Anthropic response has 'content' (list) or 'type' (error)
        if "content" not in data and "type" not in data:
            raise api_error(
                502,
                f"engine returned invalid Anthropic response shape: {list(data.keys())}"
            )
    
    _record_nonstream_usage(ctx, model, data, protocol)
    return JSONResponse(content=data, status_code=upstream.status_code)


async def _stream_with_accounting(
    client: httpx.AsyncClient,
    stream_ctx: AbstractAsyncContextManager[httpx.Response],
    upstream: httpx.Response,
    ctx: accounts.WorkspaceContext,
    model: str,
    request_id: int,
    protocol: str,
) -> AsyncIterator[bytes]:
    chunks: list[bytes] = []
    try:
        async for chunk in upstream.aiter_bytes():
            chunks.append(chunk)
            yield chunk
    finally:
        await stream_ctx.__aexit__(None, None, None)
        await client.aclose()
        live.end(request_id)
    try:
        # Usage accounting is best-effort: it must never break or delay the stream.
        text = b"".join(chunks).decode("utf-8", errors="replace")
        tokens = _stream_usage(text, protocol)
        if tokens is not None:
            usage.record_usage(
                ctx.workspace_id,
                model,
                tokens[0],
                tokens[1],
                key_id=ctx.key_id,
            )
    except Exception:  # sanctioned: accounting must never break the stream
        pass


async def _forward_stream(
    url: str,
    body: dict[str, object],
    ctx: accounts.WorkspaceContext,
    model: str,
    request_id: int,
    protocol: str,
) -> StreamingResponse:
    if protocol == "openai":
        # OpenAI streams only carry usage when explicitly requested.
        stream_options = body.get("stream_options")
        merged = dict(stream_options) if isinstance(stream_options, dict) else {}
        merged["include_usage"] = True
        body["stream_options"] = merged
    client = httpx.AsyncClient(timeout=_TIMEOUT)
    stream_ctx = client.stream("POST", url, json=body)
    try:
        upstream = await stream_ctx.__aenter__()
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        await client.aclose()
        live.end(request_id)
        raise api_error(502, f"could not connect to engine: {exc}") from exc
    return StreamingResponse(
        _stream_with_accounting(
            client, stream_ctx, upstream, ctx, model, request_id, protocol
        ),
        status_code=upstream.status_code,
        media_type="text/event-stream",
    )


async def _forward(
    request: Request, endpoint: str, ctx: accounts.WorkspaceContext, protocol: str
) -> JSONResponse | StreamingResponse:
    body = await request.json()
    if not isinstance(body, dict):
        raise api_error(400, "request body must be a JSON object")
    try:
        model_name, model_ref = _resolve_model(body)
        request_id = live.begin(ctx.username, ctx.workspace_name, model_name, endpoint)
        try:
            base_url = _ensure_base_url(model_ref)
        except Exception:
            live.end(request_id)
            raise
        url = f"{base_url}/{endpoint}"
        # count_tokens never streams; /messages and the OpenAI endpoints do.
        is_streamable = endpoint in ("messages", "chat/completions", "completions")
        wants_stream = bool(body.get("stream")) if body.get("stream") is not None else False
        if wants_stream and is_streamable:
            return await _forward_stream(url, body, ctx, model_name, request_id, protocol)
        try:
            return await _forward_nonstream(url, body, ctx, model_name, protocol)
        finally:
            live.end(request_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise api_error(
            502, f"proxy error: {type(exc).__name__}: {exc}"
        ) from exc


@router.post("/messages", response_model=None)
async def messages(
    request: Request, ctx: WorkspaceDep
) -> JSONResponse | StreamingResponse:
    """Proxy ``POST /v1/messages`` to the active engine (primary surface)."""
    return await _forward(request, "messages", ctx, "anthropic")


@router.post("/messages/count_tokens", response_model=None)
async def messages_count_tokens(
    request: Request, ctx: WorkspaceDep
) -> JSONResponse | StreamingResponse:
    """Proxy ``POST /v1/messages/count_tokens`` to the active engine."""
    return await _forward(request, "messages/count_tokens", ctx, "anthropic")


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: Request, ctx: WorkspaceDep
) -> JSONResponse | StreamingResponse:
    """Proxy ``POST /v1/chat/completions`` (OpenAI compatibility surface)."""
    return await _forward(request, "chat/completions", ctx, "openai")


@router.post("/completions", response_model=None)
async def completions(
    request: Request, ctx: WorkspaceDep
) -> JSONResponse | StreamingResponse:
    """Proxy ``POST /v1/completions`` (OpenAI compatibility surface)."""
    return await _forward(request, "completions", ctx, "openai")
