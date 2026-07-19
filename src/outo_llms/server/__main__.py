"""Entry point: ``python -m outo_llms.server`` starts the uvicorn server."""

from __future__ import annotations

import uvicorn

from ..core import certs
from ..core.config import load_config


def main() -> None:
    """Load config and serve the app (HTTP or HTTPS per config)."""
    cfg = load_config()
    scheme = "https" if cfg.server.https else "http"
    print(f"outo-llms serving on {scheme}://{cfg.server.host}:{cfg.server.port}", flush=True)

    app = "outo_llms.server.app:create_app"
    if cfg.server.https:
        common_name = cfg.server.domain or (
            cfg.server.host if cfg.server.host != "0.0.0.0" else "localhost"
        )
        cert, key = certs.ensure_server_cert(common_name)
        uvicorn.run(
            app,
            factory=True,
            host=cfg.server.host,
            port=cfg.server.port,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
        )
    else:
        uvicorn.run(app, factory=True, host=cfg.server.host, port=cfg.server.port)


if __name__ == "__main__":
    main()
