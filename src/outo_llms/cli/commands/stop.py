"""`outo-llms stop` - stop the background API server."""

from __future__ import annotations

import typer
from rich.console import Console

from ...core import process

console = Console()


def stop() -> None:
    """Stop the outo-llms API server."""
    try:
        stopped = process.stop_server()
    except RuntimeError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    if stopped:
        console.print("[green]server stopped.[/]")
    else:
        console.print("[yellow]server was not running - nothing to stop.[/]")
