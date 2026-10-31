"""Anthropic <-> OpenAI translation for engines without native /v1/messages.

llama-cpp-python's server only exposes the OpenAI chat format. The proxy
uses these pure functions to translate an incoming Anthropic request to an
OpenAI chat/completions request before forwarding, and the engine's OpenAI
response back to an Anthropic Messages response (and OpenAI SSE chunks to
Anthropic SSE events) on the way out. No I/O happens here, so the functions
are trivially testable.
"""

from __future__ import annotations

import json
from typing import Any

# Anthropic finish reasons -> OpenAI finish_reason
_ANTHROPIC_STOP = {"end_turn": "stop", "max_tokens": "length", "tool_use": "tool_calls"}
_OPENAI_STOP = {v: k for k, v in _ANTHROPIC_STOP.items()}


def _text_of(content: Any) -> str:
    """Flatten a content value (string or list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _system_to_messages(system: Any) -> list[dict[str, Any]]:
    """Anthropic `system` (string or block list) -> OpenAI system messages."""
    if system is None:
        return []
    text = _text_of(system)
    return [{"role": "system", "content": text}] if text else []


def _convert_message(message: Any) -> dict[str, Any] | None:
    """One Anthropic message -> one OpenAI message (text content only).

    Tool results become tool-role messages with a tool_call_id; tool_use
    blocks inside an assistant message become OpenAI tool_calls.
    """
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    content = message.get("content")
    if isinstance(content, list):
        tool_uses = [
            b for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]
        tool_results = [
            b for b in content
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]
        if tool_results:
            # Each tool_result maps to its own OpenAI tool message.
            block = tool_results[0]
            return {
                "role": "tool",
                "tool_call_id": block.get("tool_use_id", ""),
                "content": _text_of(block.get("content")),
            }
        converted: dict[str, Any] = {"role": role, "content": _text_of(content)}
        if tool_uses:
            converted["tool_calls"] = [
                {
                    "id": b.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": b.get("name", ""),
                        "arguments": json.dumps(b.get("input") or {}),
                    },
                }
                for b in tool_uses
            ]
        return converted
    return {"role": role, "content": _text_of(content)}


def _convert_tool(tool: Any) -> dict[str, Any] | None:
    """Anthropic tool definition -> OpenAI function tool definition."""
    if not isinstance(tool, dict):
        return None
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or {"type": "object"},
        },
    }


def request_to_openai(body: dict[str, Any]) -> dict[str, Any]:
    """Translate an Anthropic /v1/messages body to an OpenAI chat body."""
    messages: list[dict[str, Any]] = _system_to_messages(body.get("system"))
    for message in body.get("messages") or []:
        converted = _convert_message(message)
        if converted is not None:
            messages.append(converted)

    out: dict[str, Any] = {"messages": messages}
    passthrough = ("model", "max_tokens", "temperature", "top_p", "stream", "metadata")
    for field in passthrough:
        if field in body and body[field] is not None:
            out[field] = body[field]
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]
    if body.get("tools"):
        tools = [t for t in (_convert_tool(t) for t in body["tools"]) if t]
        if tools:
            out["tools"] = tools
    choice = body.get("tool_choice")
    if isinstance(choice, dict):
        kind = choice.get("type")
        if kind in ("auto", "any"):
            out["tool_choice"] = "auto" if kind == "auto" else "required"
        elif kind == "tool" and choice.get("name"):
            out["tool_choice"] = {
                "type": "function",
                "function": {"name": choice["name"]},
            }
    return out


def response_to_anthropic(data: dict[str, Any], model: str) -> dict[str, Any]:
    """Translate an OpenAI chat completion response to Anthropic Messages."""
    choices = data.get("choices") or []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first.get("message") or {}
    content: list[dict[str, Any]] = []
    text = message.get("content")
    if text:
        content.append({"type": "text", "text": text})
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            args = json.loads(function.get("arguments") or "{}")
        except ValueError:
            args = {}
        content.append({
            "type": "tool_use",
            "id": call.get("id", ""),
            "name": function.get("name", ""),
            "input": args,
        })
    usage = data.get("usage") or {}
    return {
        "id": data.get("id", "msg_translated"),
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": data.get("model", model),
        "stop_reason": _OPENAI_STOP.get(first.get("finish_reason"), "end_turn"),
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


def sse_to_anthropic(text: str, model: str) -> str:
    """Translate a captured OpenAI SSE stream to Anthropic SSE events.

    The proxy buffers the whole stream for usage accounting anyway, so the
    conversion runs once over the full text and emits a well-formed
    Anthropic event sequence.
    """
    message_id = "msg_translated"
    input_tokens = 0
    output_tokens = 0
    text_parts: list[str] = []
    stop_reason = "end_turn"
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):].strip()
        if payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        message_id = obj.get("id", message_id)
        usage = obj.get("usage")
        if isinstance(usage, dict):
            input_tokens = int(usage.get("prompt_tokens") or input_tokens)
            output_tokens = int(usage.get("completion_tokens") or output_tokens)
        for choice in obj.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                text_parts.append(delta["content"])
            if choice.get("finish_reason"):
                stop_reason = _OPENAI_STOP.get(choice["finish_reason"], "end_turn")

    events: list[str] = []

    def emit(event: str, payload: dict[str, Any]) -> None:
        events.append(f"event: {event}\ndata: {json.dumps(payload)}\n")

    emit("message_start", {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "usage": {"input_tokens": input_tokens, "output_tokens": 0},
        },
    })
    emit("content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""},
    })
    if text_parts:
        emit("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "".join(text_parts)},
        })
    emit("content_block_stop", {"type": "content_block_stop", "index": 0})
    emit("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": output_tokens},
    })
    emit("message_stop", {"type": "message_stop"})
    return "\n".join(events) + "\n"
