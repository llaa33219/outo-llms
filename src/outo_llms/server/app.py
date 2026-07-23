"""FastAPI application factory for the outo-llms server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException

import outo_llms

from . import db, proxy
from .routes import account, keys, live, status, usage, workspaces

_STATIC_DIR = Path(__file__).parent / "ui" / "static"
_INDEX_FILE = "index.html"
_MEDIA_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}
_NO_CACHE = {"Cache-Control": "no-cache"}


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    yield


def _ui_404(message: str) -> JSONResponse:
    """Plain 404 body for missing web UI assets."""
    return JSONResponse(
        status_code=404,
        content={"error": {"message": message, "type": "not_found"}},
    )


def create_app() -> FastAPI:
    """Build the outo-llms FastAPI application."""
    app = FastAPI(title="outo-llms", version=outo_llms.__version__, lifespan=_lifespan)

    @app.exception_handler(HTTPException)
    def openai_shape_errors(_request: Request, exc: HTTPException) -> JSONResponse:
        """Normalize every HTTP error to the OpenAI ``{"error": {...}}`` body."""
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(
                detail, status_code=exc.status_code, headers=exc.headers
            )
        return JSONResponse(
            {"error": {"message": str(detail), "type": "invalid_request_error"}},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    app.include_router(account.router)
    app.include_router(workspaces.router)
    app.include_router(keys.router)
    app.include_router(usage.router)
    app.include_router(status.router)
    app.include_router(live.router)
    app.include_router(proxy.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_model=None)
    def spa_index() -> FileResponse | JSONResponse:
        """Serve the SPA entry point, or a clear 404 when assets are absent."""
        index = _STATIC_DIR / _INDEX_FILE
        if not index.is_file():
            return _ui_404("web UI assets are missing from this install")
        return FileResponse(index)

    @app.get("/ui/{filename}", response_model=None)
    def spa_asset(filename: str) -> FileResponse | JSONResponse:
        """Serve a whitelisted SPA asset; never anything outside the static dir."""
        static_dir = _STATIC_DIR
        if not static_dir.is_dir():
            return _ui_404("web UI assets are missing from this install")
        candidate = (static_dir / filename).resolve()
        if not candidate.is_relative_to(static_dir.resolve()):
            return _ui_404(f"web UI asset {filename!r} was not found")
        whitelist = {path.name for path in static_dir.iterdir() if path.is_file()}
        if filename not in whitelist:
            return _ui_404(f"web UI asset {filename!r} was not found")
        media_type = _MEDIA_TYPES.get(candidate.suffix)
        return FileResponse(candidate, media_type=media_type, headers=_NO_CACHE)

    return app
