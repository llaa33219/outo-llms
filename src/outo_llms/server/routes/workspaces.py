"""Workspace routes: create and list workspaces for the authenticated user."""

from __future__ import annotations

from fastapi import APIRouter

from .. import accounts
from ..deps import UserDep, openai_error
from ..schemas import Limits, WorkspaceCreate, WorkspaceOut

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceOut)
def create_workspace(
    body: WorkspaceCreate,
    ctx: UserDep,
) -> WorkspaceOut:
    """Create a new workspace owned by the authenticated user."""
    try:
        result = accounts.create_workspace(ctx.user_id, body.name)
    except ValueError as exc:
        raise openai_error(409, str(exc)) from exc
    return WorkspaceOut.model_validate(result)


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(
    ctx: UserDep,
) -> list[WorkspaceOut]:
    """List every workspace owned by the authenticated user."""
    return [
        WorkspaceOut.model_validate(ws) for ws in accounts.list_workspaces(ctx.user_id)
    ]


@router.patch("/{name}", response_model=WorkspaceOut)
def update_workspace_limits(
    name: str,
    body: Limits,
    ctx: UserDep,
) -> WorkspaceOut:
    """Set or clear token limits on an owned workspace.

    Only the fields present in the request body change; an explicit null
    clears that period's limit.
    """
    for ws in accounts.list_workspaces(ctx.user_id):
        if ws["name"] != name:
            continue
        updates = {field: getattr(body, field) for field in body.model_fields_set}
        if not updates:
            raise openai_error(400, "request body must set at least one limit field")
        accounts.set_workspace_limits(ws["id"], updates)
        for refreshed in accounts.list_workspaces(ctx.user_id):
            if refreshed["id"] == ws["id"]:
                return WorkspaceOut.model_validate(refreshed)
    raise openai_error(404, f"workspace {name!r} not found")
