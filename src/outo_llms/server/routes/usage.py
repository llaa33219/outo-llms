"""Usage route: per-workspace or per-user metering summary."""

from __future__ import annotations

from fastapi import APIRouter

from .. import accounts, usage
from ..deps import UserDep, openai_error
from ..schemas import UsageSummary

router = APIRouter(prefix="/v1/usage", tags=["usage"])


@router.get("", response_model=UsageSummary)
def get_usage(ctx: UserDep, workspace: str | None = None) -> UsageSummary:
    """Usage for one owned workspace, or aggregated across all of them.

    With ``?workspace=<name>`` the summary covers that workspace only (404
    when the authenticated user does not own it); without the parameter it
    aggregates across every workspace the user owns.
    """
    if workspace is None:
        return UsageSummary.model_validate(usage.usage_summary_for_user(ctx.user_id))
    for ws in accounts.list_workspaces(ctx.user_id):
        if ws["name"] == workspace:
            return UsageSummary.model_validate(usage.usage_summary(ws["id"]))
    raise openai_error(404, f"workspace {workspace!r} not found")
