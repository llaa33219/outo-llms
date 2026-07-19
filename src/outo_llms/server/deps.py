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


def bearer_token(request: Request) -> str:
    """Raw Bearer token from the Authorization header, or a 401."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise openai_error(401, "missing or malformed Authorization header")
    return token.strip()


def require_user(request: Request) -> accounts.UserSession:
    """Authenticate via ``Authorization: Bearer <session_token>`` -> user session."""
    session = accounts.verify_session(bearer_token(request))
    if session is None:
        raise openai_error(401, "invalid or expired session token")
    return session


UserDep = Annotated[accounts.UserSession, Depends(require_user)]


def require_session_or_workspace(
    request: Request,
) -> accounts.UserSession | accounts.WorkspaceContext:
    """Authenticate with either a session token (web UI) or an API key (clients)."""
    token = bearer_token(request)
    if token.startswith("outo_st_"):
        session = accounts.verify_session(token)
        if session is None:
            raise openai_error(401, "invalid or expired session token")
        return session
    ctx = accounts.verify_key(token)
    if ctx is None:
        raise openai_error(401, "invalid or revoked API key")
    return ctx


SessionOrWorkspaceDep = Annotated[
    accounts.UserSession | accounts.WorkspaceContext,
    Depends(require_session_or_workspace),
]
