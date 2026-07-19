"""Account routes: open signup/login plus session-authenticated self-management."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import accounts
from ..deps import UserDep, bearer_token, openai_error
from ..schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChange,
    SignupRequest,
    SignupResponse,
)

router = APIRouter(prefix="/v1/account", tags=["account"])


@router.post("/signup", response_model=SignupResponse)
def signup(body: SignupRequest) -> SignupResponse:
    """Open signup: create a user, default workspace, first key, and session."""
    try:
        result = accounts.signup(body.username, body.password)
    except ValueError as exc:
        raise openai_error(409, str(exc)) from exc
    return SignupResponse.model_validate(result)


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    """Open login: verify credentials and return a new session token."""
    try:
        result = accounts.login(body.username, body.password)
    except ValueError as exc:
        raise openai_error(401, str(exc)) from exc
    return LoginResponse.model_validate(result)


@router.post("/logout")
def logout(request: Request, _session: UserDep) -> dict[str, bool]:
    """Revoke the calling session."""
    accounts.revoke_session(bearer_token(request))
    return {"revoked": True}


@router.get("/me")
def me(ctx: UserDep) -> dict[str, object]:
    """Return the authenticated user's identity and workspaces."""
    return {
        "user_id": ctx.user_id,
        "username": ctx.username,
        "workspaces": accounts.list_workspaces(ctx.user_id),
    }


@router.post("/password")
def change_password(body: PasswordChange, ctx: UserDep) -> dict[str, bool]:
    """Change the authenticated user's password."""
    try:
        accounts.change_password(ctx.user_id, body.current_password, body.new_password)
    except ValueError as exc:
        raise openai_error(401, str(exc)) from exc
    return {"changed": True}
