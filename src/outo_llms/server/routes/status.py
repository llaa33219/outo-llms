"""Status route: read-only server, engine, and row-count snapshot for the web UI."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter

import outo_llms

from .. import db
from ..core import config as config_mod
from ..deps import WorkspaceDep
from ..schemas import Counts, EngineStatus, ServerInfo, StatusOut

router = APIRouter(prefix="/v1/status", tags=["status"])


def _count(conn: sqlite3.Connection, table: str) -> int:
    """Row count of ``table``; COUNT(*) always yields exactly one row."""
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(row["n"]) if row is not None else 0


def _engine_status(engine_name: str) -> EngineStatus:
    """Live engine snapshot, degrading to 'not installed' when unavailable."""
    try:
        from outo_llms.engines.manager import EngineManager

        return EngineStatus.model_validate(EngineManager().status())
    except Exception:  # status must never 500: report the engine as absent
        return EngineStatus(
            engine=engine_name or "unknown",
            installed=False,
            running=False,
            pid=None,
            model=None,
            port=None,
            base_url=None,
        )


@router.get("", response_model=StatusOut)
def get_status(ctx: WorkspaceDep) -> StatusOut:
    """Server, engine, and row-count snapshot for the authenticated caller."""
    cfg = config_mod.load_config()
    with db.get_conn() as conn:
        counts = Counts(
            users=_count(conn, "users"),
            workspaces=_count(conn, "workspaces"),
            models=_count(conn, "models"),
        )
    return StatusOut(
        version=outo_llms.__version__,
        server=ServerInfo(
            host=cfg.server.host,
            port=cfg.server.port,
            https=cfg.server.https,
            domain=cfg.server.domain,
        ),
        engine=_engine_status(cfg.engine.name),
        counts=counts,
    )
