"""Accounts: users, workspaces, and API keys.

API keys are issued as ``outo_sk_<random>`` and only their SHA-256 hex
digest is stored; the plaintext is shown exactly once at creation time.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from typing import TypedDict

from . import db

_KEY_PREFIX = "outo_sk_"


class WorkspaceDict(TypedDict):
    id: int
    name: str
    created_at: str


class KeyDict(TypedDict):
    id: int
    label: str
    created_at: str
    revoked: bool


@dataclass(frozen=True)
class WorkspaceContext:
    """Identity resolved from a valid API key."""

    workspace_id: int
    workspace_name: str
    user_id: int
    username: str


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def signup(username: str) -> dict[str, object]:
    """Create a user, their ``default`` workspace, and the first API key."""
    db.init_db()
    with db.get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, created_at) VALUES (?, ?)",
                (username, db.utcnow()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"username {username!r} is already taken") from exc
        user_id = cur.lastrowid
        if user_id is None:  # pragma: no cover - sqlite always sets it on INSERT
            raise RuntimeError("failed to create user")
        conn.execute(
            "INSERT INTO workspaces (user_id, name, created_at) VALUES (?, ?, ?)",
            (user_id, "default", db.utcnow()),
        )
    api_key = create_key(_default_workspace_id(user_id))
    return {
        "user_id": user_id,
        "username": username,
        "workspace": "default",
        "api_key": api_key,
    }


def _default_workspace_id(user_id: int) -> int:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM workspaces WHERE user_id = ? AND name = 'default'",
            (user_id,),
        ).fetchone()
    if row is None:  # pragma: no cover - impossible right after signup
        raise RuntimeError(f"user {user_id} has no default workspace")
    return int(row["id"])


def create_workspace(user_id: int, name: str) -> WorkspaceDict:
    """Create a workspace for ``user_id``; duplicates raise ``ValueError``."""
    db.init_db()
    with db.get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO workspaces (user_id, name, created_at) VALUES (?, ?, ?)",
                (user_id, name, db.utcnow()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"workspace {name!r} already exists for this user"
            ) from exc
        row = conn.execute(
            "SELECT id, name, created_at FROM workspaces WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    if row is None:  # pragma: no cover - we just inserted it
        raise RuntimeError("failed to create workspace")
    return WorkspaceDict(
        id=int(row["id"]), name=row["name"], created_at=row["created_at"]
    )


def list_workspaces(user_id: int) -> list[WorkspaceDict]:
    """All workspaces owned by ``user_id``."""
    db.init_db()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM workspaces WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [
        WorkspaceDict(
            id=int(row["id"]), name=row["name"], created_at=row["created_at"]
        )
        for row in rows
    ]


def create_key(workspace_id: int, label: str = "") -> str:
    """Issue a new API key for a workspace; returns the plaintext once."""
    db.init_db()
    plaintext = _KEY_PREFIX + secrets.token_urlsafe(24)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO api_keys (workspace_id, key_hash, label, created_at)"
            " VALUES (?, ?, ?, ?)",
            (workspace_id, _hash_key(plaintext), label, db.utcnow()),
        )
    return plaintext


def list_keys(workspace_id: int) -> list[KeyDict]:
    """Key metadata for a workspace. Never includes the hash."""
    db.init_db()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, label, created_at, revoked FROM api_keys"
            " WHERE workspace_id = ? ORDER BY id",
            (workspace_id,),
        ).fetchall()
    return [
        KeyDict(
            id=int(row["id"]),
            label=row["label"],
            created_at=row["created_at"],
            revoked=bool(row["revoked"]),
        )
        for row in rows
    ]


def revoke_key(key_id: int, workspace_id: int) -> bool:
    """Revoke a key owned by ``workspace_id``; False if no such key."""
    db.init_db()
    with db.get_conn() as conn:
        cur = conn.execute(
            "UPDATE api_keys SET revoked = 1 WHERE id = ? AND workspace_id = ?",
            (key_id, workspace_id),
        )
    return cur.rowcount > 0


def verify_key(key: str) -> WorkspaceContext | None:
    """Resolve an API key to its workspace context, or None if invalid."""
    db.init_db()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT k.workspace_id, w.name AS workspace_name, w.user_id, u.username"
            " FROM api_keys k"
            " JOIN workspaces w ON w.id = k.workspace_id"
            " JOIN users u ON u.id = w.user_id"
            " WHERE k.key_hash = ? AND k.revoked = 0",
            (_hash_key(key),),
        ).fetchone()
    if row is None:
        return None
    return WorkspaceContext(
        workspace_id=int(row["workspace_id"]),
        workspace_name=row["workspace_name"],
        user_id=int(row["user_id"]),
        username=row["username"],
    )
