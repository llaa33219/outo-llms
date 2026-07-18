"""Usage route: per-workspace metering summary."""

from __future__ import annotations

from fastapi import APIRouter

from .. import usage
from ..deps import WorkspaceDep
from ..schemas import UsageSummary

router = APIRouter(prefix="/v1/usage", tags=["usage"])


@router.get("", response_model=UsageSummary)
def get_usage(ctx: WorkspaceDep) -> UsageSummary:
    """Aggregated usage for the authenticated key's workspace."""
    return UsageSummary.model_validate(usage.usage_summary(ctx.workspace_id))
