"""FastAPI application factory for the outo-llms server."""

from __future__ import annotations

import html
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

import outo_llms

from . import db, proxy, registry
from .routes import account, keys, usage, workspaces


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    yield


def _engine_status() -> dict[str, object]:
    from outo_llms.engines.manager import EngineManager

    return EngineManager().status()


def _dashboard() -> str:
    try:
        status = _engine_status()
        engine = html.escape(str(status.get("engine") or "unknown"))
        model = html.escape(str(status.get("model") or "none loaded"))
        running = "running" if status.get("running") else "stopped"
        engine_html = (
            f"<p><span class='label'>engine</span> {engine}"
            f" <span class='muted'>({running})</span></p>"
            f"<p><span class='label'>model</span> {model}</p>"
        )
    except Exception:  # engines machinery unavailable (e.g. not installed yet)
        engine_html = "<p><span class='label'>engine</span> unavailable</p>"

    with db.get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM workspaces").fetchone()
    workspace_count = int(row["n"]) if row is not None else 0
    model_count = len(registry.list_models())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>outo-llms</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ background: #0d1117; color: #e6edf3; font-family: system-ui, sans-serif;
         margin: 0; display: grid; place-items: center; min-height: 100vh; }}
  main {{ width: min(42rem, 90vw); padding: 2rem; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .25rem; }}
  .muted {{ color: #8b949e; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px;
           padding: 1.25rem 1.5rem; margin-top: 1.25rem; }}
  .label {{ color: #8b949e; display: inline-block; min-width: 7.5rem; }}
  p {{ margin: .4rem 0; }}
  a {{ color: #58a6ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .ok {{ color: #3fb950; }}
</style>
</head>
<body>
<main>
  <h1>outo-llms</h1>
  <p class="muted">local LLMs behind your own managed API server &middot; v{outo_llms.__version__}</p>
  <div class="card">
    <p><span class="label">status</span> <span class="ok">ok</span></p>
    {engine_html}
    <p><span class="label">workspaces</span> {workspace_count}</p>
    <p><span class="label">models</span> {model_count}</p>
  </div>
  <div class="card">
    <p><a href="/docs">API docs (Swagger UI)</a></p>
    <p><a href="/healthz">/healthz</a></p>
  </div>
</main>
</body>
</html>"""


def create_app() -> FastAPI:
    """Build the outo-llms FastAPI application."""
    app = FastAPI(title="outo-llms", version=outo_llms.__version__, lifespan=_lifespan)

    app.include_router(account.router)
    app.include_router(workspaces.router)
    app.include_router(keys.router)
    app.include_router(usage.router)
    app.include_router(proxy.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _dashboard()

    return app
