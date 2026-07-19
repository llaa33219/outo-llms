"""Model registry: names clients use, mapped to engine-loadable sources."""

from __future__ import annotations

import sqlite3

from ..engines.base import ModelRef
from . import db

_KINDS = ("hf", "gguf")


def add_model(name: str, source: str, kind: str) -> None:
    """Register a model. ``kind`` must be ``hf`` or ``gguf``; names are unique."""
    db.init_db()
    if kind not in _KINDS:
        raise ValueError(f"kind must be one of {_KINDS}, got {kind!r}")
    with db.get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO models (name, source, kind, created_at) VALUES (?, ?, ?, ?)",
                (name, source, kind, db.utcnow()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"model {name!r} is already registered") from exc


def get_model(name: str) -> ModelRef | None:
    """Look up a registered model by name."""
    db.init_db()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT name, source, kind FROM models WHERE name = ?",
            (name,),
        ).fetchone()
    if row is None:
        return None
    return ModelRef(name=row["name"], source=row["source"], kind=row["kind"])


def list_models() -> list[dict[str, object]]:
    """Every registered model, oldest first."""
    db.init_db()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT name, source, kind, created_at FROM models ORDER BY id"
        ).fetchall()
    return [
        {
            "name": row["name"],
            "source": row["source"],
            "kind": row["kind"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def remove_model(name: str) -> bool:
    """Remove a model from the registry; False if it was not registered."""
    db.init_db()
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM models WHERE name = ?", (name,))
    return cur.rowcount > 0


def update_source(name: str, source: str) -> bool:
    """Point a registered model at a different source (e.g. repo:file)."""
    db.init_db()
    with db.get_conn() as conn:
        cur = conn.execute(
            "UPDATE models SET source = ? WHERE name = ?", (source, name)
        )
    return cur.rowcount > 0
