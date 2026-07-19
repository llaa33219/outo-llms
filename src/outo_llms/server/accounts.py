"""Accounts: users, passwords, sessions, workspaces, and API keys.

API keys are issued as ``outo_sk_<random>`` and only their SHA-256 hex
digest is stored; the plaintext is shown exactly once at creation time.
API keys authorize inference only.

Account management uses username + password with server-side sessions.
Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes; session tokens
are issued as ``outo_st_<random>`` and, like API keys, only their SHA-256
hex digest is stored. Plaintext passwords and tokens are never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import TypedDict

from . import db

_KEY_PREFIX = "outo_sk_"
_SESSION_PREFIX = "outo_st_"
_SESSION_TTL = timedelta(days=14)
_PBKDF2_ITERATIONS = 600_000
_PASSWORD_MIN_LENGTH = 8
_PASSWORD_MAX_LENGTH = 256
_USERNAME_MAX_LENGTH = 64


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


@dataclass(frozen=True)
class UserSession:
    """Identity resolved from a valid session token."""

    user_id: int
    username: str


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str) -> str:
    """Salted PBKDF2-HMAC-SHA256 hash in ``pbkdf2_sha256$iter$salt$hash`` form."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a stored PBKDF2 hash."""
    try:
        scheme, iterations, salt_hex, hash_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except ValueError:  # malformed stored hash: wrong arity, bad int, bad hex
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A valid-format hash that no password matches, for timing equalization."""
    return _hash_password(secrets.token_urlsafe(16))


def _validate_credentials_shape(username: str, password: str) -> None:
    """Enforce the signup credential bounds; ``ValueError`` on violation."""
    if not 1 <= len(username) <= _USERNAME_MAX_LENGTH:
        raise ValueError(
            f"username must be between 1 and {_USERNAME_MAX_LENGTH} characters"
        )
    if not _PASSWORD_MIN_LENGTH <= len(password) <= _PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"password must be between {_PASSWORD_MIN_LENGTH} and "
            f"{_PASSWORD_MAX_LENGTH} characters"
        )


def signup(username: str, password: str) -> dict[str, object]:
    """Create a user, their ``default`` workspace, first API key, and session."""
    _validate_credentials_shape(username, password)
    db.init_db()
    with db.get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, created_at)"
                " VALUES (?, ?, ?)",
                (username, _hash_password(password), db.utcnow()),
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
    api_key = str(create_key(_default_workspace_id(user_id))["api_key"])
    session_token = create_session(user_id)
    return {
        "user_id": user_id,
        "username": username,
        "workspace": "default",
        "api_key": api_key,
        "session_token": session_token,
    }


def login(username: str, password: str) -> dict[str, object]:
    """Verify credentials and open a session.

    Failure shape is constant: credentials are always checked against a
    hash (a dummy one when the user is missing or has no password), and a
    single generic error message is raised so the response reveals nothing
    about which usernames exist.
    """
    db.init_db()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    stored = row["password_hash"] if row is not None else None
    ok = _verify_password(password, stored if stored else _dummy_hash())
    if row is None or not ok:
        raise ValueError("invalid username or password")
    user_id = int(row["id"])
    return {
        "session_token": create_session(user_id),
        "user_id": user_id,
        "username": username,
        "workspaces": list_workspaces(user_id),
    }


def create_session(user_id: int) -> str:
    """Open a session for ``user_id``; returns the plaintext token once."""
    db.init_db()
    token = _SESSION_PREFIX + secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, token_hash, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (
                user_id,
                _hash_token(token),
                now.isoformat(),
                (now + _SESSION_TTL).isoformat(),
            ),
        )
    return token


def verify_session(token: str) -> UserSession | None:
    """Resolve a session token to its user, or None if invalid or expired.

    Expired sessions are deleted lazily here, on access.
    """
    db.init_db()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT s.id, s.user_id, s.expires_at, u.username"
            " FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ?",
            (_hash_token(token),),
        ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            conn.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
            return None
    return UserSession(user_id=int(row["user_id"]), username=row["username"])


def revoke_session(token: str) -> bool:
    """Revoke a session by its plaintext token; False if no such session."""
    db.init_db()
    with db.get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE token_hash = ?",
            (_hash_token(token),),
        )
    return cur.rowcount > 0


def change_password(user_id: int, current: str, new: str) -> None:
    """Change a user's password; ``ValueError`` on wrong current or weak new."""
    if not _PASSWORD_MIN_LENGTH <= len(new) <= _PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"new password must be between {_PASSWORD_MIN_LENGTH} and "
            f"{_PASSWORD_MAX_LENGTH} characters"
        )
    db.init_db()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        stored = row["password_hash"] if row is not None else None
        if not stored or not _verify_password(current, stored):
            raise ValueError("current password is incorrect")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_password(new), user_id),
        )


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


def create_key(workspace_id: int, label: str = "") -> dict[str, object]:
    """Issue a new API key for a workspace; returns id and plaintext once."""
    db.init_db()
    plaintext = _KEY_PREFIX + secrets.token_urlsafe(24)
    with db.get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO api_keys (workspace_id, key_hash, label, created_at)"
            " VALUES (?, ?, ?, ?)",
            (workspace_id, _hash_key(plaintext), label, db.utcnow()),
        )
    return {"id": cursor.lastrowid, "api_key": plaintext}


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
