"""Account routes: open signup and authenticated self-info."""

from __future__ import annotations

from fastapi import APIRouter

from .. import accounts
from ..deps import WorkspaceDep, openai_error
from ..schemas import SignupRequest, SignupResponse

router = APIRouter(prefix="/v1/account", tags=["account"])


@router.post("/signup", response_model=SignupResponse)
def signup(body: SignupRequest) -> SignupResponse:
    """Open signup: create a user, default workspace, and first API key."""
    try:
        result = accounts.signup(body.username)
    except ValueError as exc:
        raise openai_error(409, str(exc)) from exc
    return SignupResponse.model_validate(result)


@router.get("/me")
def me(ctx: WorkspaceDep) -> dict[str, object]:
    """Return the authenticated user's identity and workspaces."""
    return {
        "user_id": ctx.user_id,
        "username": ctx.username,
        "workspaces": accounts.list_workspaces(ctx.user_id),
    }
