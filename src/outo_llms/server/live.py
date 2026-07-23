"""In-flight inference request registry.

Tracks requests currently being proxied to the engine so ``GET /v1/live``
can report who is asking right now. The registry is a plain module-level
dict keyed by a monotonically increasing id; single dict operations and
``itertools.count`` increments are atomic under the GIL, which is enough
for the proxy's async, single-process usage - no lock needed.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass

_requests: dict[int, InflightRequest] = {}
_ids = itertools.count(1)


@dataclass(frozen=True)
class InflightRequest:
    """One inference request currently in flight."""

    id: int
    user: str
    workspace: str
    model: str
    endpoint: str
    started: float


def begin(user: str, workspace: str, model: str, endpoint: str) -> int:
    """Register a request as in-flight; returns its id for :func:`end`."""
    request_id = next(_ids)
    _requests[request_id] = InflightRequest(
        id=request_id,
        user=user,
        workspace=workspace,
        model=model,
        endpoint=endpoint,
        started=time.monotonic(),
    )
    return request_id


def end(request_id: int) -> None:
    """Remove ``request_id`` from the registry; idempotent."""
    _requests.pop(request_id, None)


def snapshot() -> dict[str, object]:
    """Current in-flight requests, oldest first, with elapsed seconds."""
    now = time.monotonic()
    entries = sorted(_requests.values(), key=lambda req: req.started)
    return {
        "count": len(entries),
        "requests": [
            {
                "user": req.user,
                "workspace": req.workspace,
                "model": req.model,
                "endpoint": req.endpoint,
                "elapsed_seconds": round(now - req.started, 1),
            }
            for req in entries
        ],
    }
