"""`outo-llms start` - start the API server in the background."""

from __future__ import annotations

import typer
from rich.console import Console

from ...core import process

console = Console()


def start() -> None:
    """Start the outo-llms API server in the background."""
    try:
        process.start_server()
    except RuntimeError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print("[green]server started[/] - inspect it with `outo-llms status`.")
