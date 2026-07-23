"""Live-activity route: engine snapshot, in-flight requests, per-model totals."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ...core import config as config_mod
from .. import live, usage
from ..deps import UserDep
from ..schemas import Inflight, LiveEngine, LiveOut, ModelCalls

router = APIRouter(prefix="/v1/live", tags=["live"])


def _uptime_seconds(loaded_at: str | None, running: bool) -> int | None:
    """Whole seconds since the model was loaded; None when not running."""
    if loaded_at is None or not running:
        return None
    loaded = datetime.fromisoformat(loaded_at)
    return max(0, int((datetime.now(timezone.utc) - loaded).total_seconds()))


def _engine_live(engine_name: str) -> LiveEngine:
    """Live engine snapshot, degrading to 'not running' when unavailable."""
    try:
        from outo_llms.engines.manager import EngineManager

        manager = EngineManager()
        status = manager.status()
        running = bool(status["running"])
        loaded_at = manager.loaded_at() if running else None
        model = status["model"]
        port = status["port"]
        return LiveEngine(
            engine=str(status["engine"]),
            running=running,
            model=str(model) if model is not None else None,
            port=int(port) if port is not None else None,
            loaded_at=loaded_at,
            uptime_seconds=_uptime_seconds(loaded_at, running),
        )
    except Exception:  # live status must never 500: report engine as absent
        return LiveEngine(
            engine=engine_name or "unknown",
            running=False,
            model=None,
            port=None,
            loaded_at=None,
            uptime_seconds=None,
        )


@router.get("", response_model=LiveOut)
def get_live(ctx: UserDep) -> LiveOut:
    """Live activity snapshot for the authenticated caller.

    Cheap to poll: engine state and usage totals are file/SQLite reads,
    never engine subprocess calls.
    """
    cfg = config_mod.load_config()
    return LiveOut(
        engine=_engine_live(cfg.engine.name),
        inflight=Inflight.model_validate(live.snapshot()),
        models=[ModelCalls.model_validate(row) for row in usage.usage_by_model()],
    )
