"""`outo-llms restart` - restart the background API server."""

from __future__ import annotations

import typer
from rich.console import Console

from ...core import process

console = Console()


def restart() -> None:
    """Restart the outo-llms API server."""
    try:
        process.restart_server()
    except RuntimeError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print("[green]server restarted[/] - inspect it with `outo-llms status`.")
