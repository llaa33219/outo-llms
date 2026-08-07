"""Token-limit windows and enforcement for API keys and workspaces.

Each key and each workspace carries four independently settable token
limits (NULL = unlimited), summed from the usage ledger:

- ``total``: every recorded token, all time;
- ``monthly``: the current UTC calendar month;
- ``weekly``: the current ISO week (Monday 00:00 UTC);
- ``five_hour``: a rolling window of the last five hours.

Checks run before the proxy forwards a request; a request passes only
when neither its key nor its workspace has reached any configured limit.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import db

PERIODS = ("total", "monthly", "weekly", "five_hour")


@dataclass(frozen=True)
class LimitBreach:
    """One exceeded limit: who owns it, which period, and the numbers."""

    scope: str  # "key" | "workspace"
    period: str
    limit: int
    used: int


def _window_start(period: str, now: datetime) -> str | None:
    """Inclusive ISO-8601 lower bound for ``period``; None for all time."""
    if period == "total":
        return None
    if period == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    if period == "weekly":
        monday = now - timedelta(days=now.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return (now - timedelta(hours=5)).isoformat()


def _tokens_used(
    conn: sqlite3.Connection, scope: str, scope_id: int, since: str | None
) -> int:
    column = "key_id" if scope == "key" else "workspace_id"
    query = f"SELECT COALESCE(SUM(total_tokens), 0) AS used FROM usage WHERE {column} = ?"
    params: list[object] = [scope_id]
    if since is not None:
        query += " AND created_at >= ?"
        params.append(since)
    row = conn.execute(query, params).fetchone()
    return int(row["used"])


def check_limits(key_id: int, workspace_id: int) -> LimitBreach | None:
    """First breached key or workspace limit, or None when all are clear."""
    db.init_db()
    now = datetime.now(timezone.utc)
    with db.get_conn() as conn:
        select = ", ".join(
            f"{prefix}.{column} AS {prefix}_{column}"
            for prefix in ("k", "w")
            for column in db.LIMIT_COLUMNS
        )
        row = conn.execute(
            f"SELECT {select}"
            " FROM api_keys k JOIN workspaces w ON w.id = k.workspace_id"
            " WHERE k.id = ? AND w.id = ?",
            (key_id, workspace_id),
        ).fetchone()
        if row is None:
            return None
        for scope, prefix, scope_id in (
            ("key", "k", key_id),
            ("workspace", "w", workspace_id),
        ):
            for period, column in zip(PERIODS, db.LIMIT_COLUMNS):
                limit = row[f"{prefix}_{column}"]
                if limit is None:
                    continue
                used = _tokens_used(conn, scope, scope_id, _window_start(period, now))
                if used >= int(limit):
                    return LimitBreach(scope, period, int(limit), used)
    return None
