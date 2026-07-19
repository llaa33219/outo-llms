"""OpenAI-compatible proxy: forwards inference requests to the active engine.

The upstream engine server (vLLM / llama.cpp) already speaks the OpenAI
protocol on 127.0.0.1; this router adds auth, model resolution, and usage
metering on top. ``EngineManager`` is imported lazily inside handlers so
registry-only CLI usage never pulls in the engines machinery.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..engines.base import ModelRef
from . import accounts, registry, usage
from .deps import SessionOrWorkspaceDep, WorkspaceDep, openai_error

router = APIRouter(prefix="/v1", tags=["proxy"])

_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=None)


@router.get("/models")
def list_models(ctx: SessionOrWorkspaceDep) -> dict[str, object]:
    """List registered models in the OpenAI ``GET /v1/models`` shape."""
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


def _resolve_model(body: dict[str, object]) -> tuple[str, ModelRef]:
    model_name = body.get("model")
    if not isinstance(model_name, str) or not model_name:
        raise openai_error(400, "request body is missing 'model'")
    model_ref = registry.get_model(model_name)
    if model_ref is None:
        raise openai_error(
            404,
            f"model {model_name!r} not found; add it with `outo-llms models add`",
            code="model_not_found",
        )
    return model_name, model_ref


def _ensure_base_url(model_ref: ModelRef) -> str:
    from outo_llms.engines.manager import EngineManager

    manager = EngineManager()
    if not manager.is_installed():
        raise openai_error(
            502,
            f"engine {manager.current_name()!r} is not installed; "
            f"run `outo-llms engine install {manager.current_name()}`",
        )
    try:
        return manager.ensure_running(model_ref)
    except (RuntimeError, ValueError) as exc:
        raise openai_error(502, str(exc)) from exc


def _record_nonstream_usage(
    ctx: accounts.WorkspaceContext, model: str, data: dict[str, Any]
) -> None:
    usage_data = data.get("usage")
    if not isinstance(usage_data, dict):
        usage_data = {}
    usage.record_usage(
        ctx.workspace_id,
        model,
        int(usage_data.get("prompt_tokens") or 0),
        int(usage_data.get("completion_tokens") or 0),
    )


async def _forward_nonstream(
    url: str, body: dict[str, object], ctx: accounts.WorkspaceContext, model: str
) -> JSONResponse:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            upstream = await client.post(url, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise openai_error(502, f"could not connect to engine: {exc}") from exc
    try:
        data = upstream.json()
    except ValueError as exc:
        raise openai_error(502, "engine returned an invalid response") from exc
    _record_nonstream_usage(ctx, model, data)
    return JSONResponse(content=data, status_code=upstream.status_code)


async def _stream_with_accounting(
    client: httpx.AsyncClient,
    stream_ctx: AbstractAsyncContextManager[httpx.Response],
    upstream: httpx.Response,
    ctx: accounts.WorkspaceContext,
    model: str,
) -> AsyncIterator[bytes]:
    chunks: list[bytes] = []
    try:
        async for chunk in upstream.aiter_bytes():
            chunks.append(chunk)
            yield chunk
    finally:
        await stream_ctx.__aexit__(None, None, None)
        await client.aclose()
    try:
        # Usage accounting is best-effort: it must never break or delay the stream.
        text = b"".join(chunks).decode("utf-8", errors="replace")
        final_usage: dict[str, Any] | None = None
        for line in text.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: ") :].strip()
            if payload == "[DONE]":
                continue
            obj = json.loads(payload)
            if isinstance(obj, dict) and obj.get("usage") is not None:
                final_usage = obj["usage"]
        if final_usage is not None:
            usage.record_usage(
                ctx.workspace_id,
                model,
                int(final_usage.get("prompt_tokens") or 0),
                int(final_usage.get("completion_tokens") or 0),
            )
    except Exception:  # sanctioned: accounting must never break the stream
        pass


async def _forward_stream(
    url: str, body: dict[str, object], ctx: accounts.WorkspaceContext, model: str
) -> StreamingResponse:
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
        raise openai_error(502, f"could not connect to engine: {exc}") from exc
    return StreamingResponse(
        _stream_with_accounting(client, stream_ctx, upstream, ctx, model),
        status_code=upstream.status_code,
        media_type="text/event-stream",
    )


async def _forward(
    request: Request, endpoint: str, ctx: accounts.WorkspaceContext
) -> JSONResponse | StreamingResponse:
    body = await request.json()
    if not isinstance(body, dict):
        raise openai_error(400, "request body must be a JSON object")
    model_name, model_ref = _resolve_model(body)
    base_url = _ensure_base_url(model_ref)
    url = f"{base_url}/{endpoint}"
    if body.get("stream"):
        return await _forward_stream(url, body, ctx, model_name)
    return await _forward_nonstream(url, body, ctx, model_name)


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: Request, ctx: WorkspaceDep
) -> JSONResponse | StreamingResponse:
    """Proxy ``POST /v1/chat/completions`` to the active engine."""
    return await _forward(request, "chat/completions", ctx)


@router.post("/completions", response_model=None)
async def completions(
    request: Request, ctx: WorkspaceDep
) -> JSONResponse | StreamingResponse:
    """Proxy ``POST /v1/completions`` to the active engine."""
    return await _forward(request, "completions", ctx)
