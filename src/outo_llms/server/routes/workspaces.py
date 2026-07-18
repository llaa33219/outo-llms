"""Workspace routes: create and list workspaces for the authenticated user."""

from __future__ import annotations

from fastapi import APIRouter

from .. import accounts
from ..deps import WorkspaceDep, openai_error
from ..schemas import WorkspaceCreate, WorkspaceOut

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceOut)
def create_workspace(
    body: WorkspaceCreate,
    ctx: WorkspaceDep,
) -> WorkspaceOut:
    """Create a new workspace owned by the authenticated user."""
    try:
        result = accounts.create_workspace(ctx.user_id, body.name)
    except ValueError as exc:
        raise openai_error(409, str(exc)) from exc
    return WorkspaceOut.model_validate(result)


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(
    ctx: WorkspaceDep,
) -> list[WorkspaceOut]:
    """List every workspace owned by the authenticated user."""
    return [
        WorkspaceOut.model_validate(ws) for ws in accounts.list_workspaces(ctx.user_id)
    ]
