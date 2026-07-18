"""Shared FastAPI dependencies and OpenAI-style error helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from . import accounts


def openai_error(
    status_code: int, message: str, *, code: str | None = None
) -> HTTPException:
    """Build an HTTPException whose detail follows the OpenAI error shape."""
    error: dict[str, str] = {"message": message, "type": "invalid_request_error"}
    if code is not None:
        error["code"] = code
    return HTTPException(status_code=status_code, detail={"error": error})


def require_workspace(request: Request) -> accounts.WorkspaceContext:
    """Authenticate via ``Authorization: Bearer <key>`` -> workspace context."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise openai_error(401, "missing or malformed Authorization header")
    ctx = accounts.verify_key(token.strip())
    if ctx is None:
        raise openai_error(401, "invalid or revoked API key")
    return ctx


WorkspaceDep = Annotated[accounts.WorkspaceContext, Depends(require_workspace)]
