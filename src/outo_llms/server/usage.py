"""Per-workspace usage metering."""

from __future__ import annotations

from . import db


def record_usage(
    workspace_id: int, model: str, prompt_tokens: int, completion_tokens: int
) -> None:
    """Append one inference request to the usage ledger."""
    db.init_db()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO usage"
            " (workspace_id, model, prompt_tokens, completion_tokens, total_tokens,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                workspace_id,
                model,
                prompt_tokens,
                completion_tokens,
                prompt_tokens + completion_tokens,
                db.utcnow(),
            ),
        )


def usage_summary(workspace_id: int) -> dict[str, object]:
    """Aggregate usage for a workspace, grouped by model."""
    db.init_db()
    with db.get_conn() as conn:
        workspace = conn.execute(
            "SELECT name FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        rows = conn.execute(
            "SELECT model, COUNT(*) AS requests,"
            " SUM(prompt_tokens) AS prompt_tokens,"
            " SUM(completion_tokens) AS completion_tokens,"
            " SUM(total_tokens) AS total_tokens"
            " FROM usage WHERE workspace_id = ? GROUP BY model ORDER BY model",
            (workspace_id,),
        ).fetchall()
    by_model: list[dict[str, object]] = []
    total_requests = 0
    total_tokens = 0
    for row in rows:
        requests = int(row["requests"])
        model_tokens = int(row["total_tokens"])
        total_requests += requests
        total_tokens += model_tokens
        by_model.append(
            {
                "model": row["model"],
                "requests": requests,
                "prompt_tokens": int(row["prompt_tokens"]),
                "completion_tokens": int(row["completion_tokens"]),
                "total_tokens": model_tokens,
            }
        )
    return {
        "workspace": workspace["name"] if workspace is not None else "",
        "total_requests": total_requests,
        "total_tokens": total_tokens,
        "by_model": by_model,
    }
