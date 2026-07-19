"""API key routes, scoped by workspace ownership."""

from __future__ import annotations

from fastapi import APIRouter

from .. import accounts
from ..deps import UserDep, openai_error
from ..schemas import KeyCreate, KeyMeta, KeyOut

router = APIRouter(prefix="/v1", tags=["keys"])


def _owned_workspace_id(user_id: int, name: str) -> int | None:
    """Id of the workspace ``name`` owned by ``user_id``, or None."""
    for ws in accounts.list_workspaces(user_id):
        if ws["name"] == name:
            return ws["id"]
    return None


@router.post("/workspaces/{name}/keys", response_model=KeyOut)
def create_key(
    name: str,
    body: KeyCreate,
    ctx: UserDep,
) -> KeyOut:
    """Issue a new API key for a workspace the authenticated user owns."""
    workspace_id = _owned_workspace_id(ctx.user_id, name)
    if workspace_id is None:
        raise openai_error(404, f"workspace {name!r} not found")
    created = accounts.create_key(workspace_id, body.label)
    return KeyOut(
        id=int(created["id"]),
        api_key=str(created["api_key"]),
        label=body.label,
        workspace=name,
    )


@router.get("/workspaces/{name}/keys", response_model=list[KeyMeta])
def list_keys(
    name: str,
    ctx: UserDep,
) -> list[KeyMeta]:
    """List key metadata (never hashes) for an owned workspace."""
    workspace_id = _owned_workspace_id(ctx.user_id, name)
    if workspace_id is None:
        raise openai_error(404, f"workspace {name!r} not found")
    return [KeyMeta.model_validate(k) for k in accounts.list_keys(workspace_id)]


@router.delete("/keys/{key_id}")
def revoke_key(
    key_id: int,
    ctx: UserDep,
) -> dict[str, bool]:
    """Revoke a key whose workspace belongs to the authenticated user."""
    for ws in accounts.list_workspaces(ctx.user_id):
        workspace_id = ws["id"]
        if any(k["id"] == key_id for k in accounts.list_keys(workspace_id)):
            accounts.revoke_key(key_id, workspace_id)
            return {"revoked": True}
    raise openai_error(404, f"key {key_id} not found")
