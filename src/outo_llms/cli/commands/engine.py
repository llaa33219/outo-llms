"""`outo-llms engine` - manage inference engines."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from ...core import process

if TYPE_CHECKING:
    from ...engines.manager import EngineManager

console = Console()

engine_app = typer.Typer(help="Manage inference engines.", no_args_is_help=True)


def _manager() -> EngineManager:
    """Build the engine manager lazily so the CLI stays importable standalone."""
    from ...engines.manager import EngineManager

    return EngineManager()


@engine_app.command("list")
def list_engines() -> None:
    """List known engines, their installed state, and the active one."""
    manager = _manager()
    active = manager.current_name()
    table = Table(title="Engines")
    table.add_column("Engine")
    table.add_column("Installed")
    table.add_column("Active")
    for name in manager.available():
        table.add_row(
            name,
            "yes" if manager.is_installed(name) else "no",
            "yes" if name == active else "",
        )
    console.print(table)


@engine_app.command("use")
def use(
    name: str = typer.Argument(..., help="Engine to make active (llamacpp or vllm)."),
) -> None:
    """Select the active engine."""
    try:
        _manager().use(name)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]active engine: {name}[/]")


@engine_app.command("install")
def install(
    name: str | None = typer.Argument(None, help="Engine to install (default: the active engine)."),
) -> None:
    """Install an engine into its own isolated virtualenv."""
    manager = _manager()
    target = name if name is not None else manager.current_name()
    try:
        manager.install(
            target,
            on_event=lambda line: console.print(line, highlight=False, markup=False),
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]engine '{target}' installed.[/]")


@engine_app.command("status")
def engine_status() -> None:
    """Show the active engine's runtime status."""
    info = _manager().status()
    table = Table(title="Engine status")
    table.add_column("Property")
    table.add_column("Value")
    for key in ("engine", "installed", "running", "pid", "model", "port", "base_url"):
        value = info.get(key)
        table.add_row(key, "-" if value is None else str(value))
    pid = process.server_pid()
    table.add_row("server running", "yes" if process.is_server_running() else "no")
    table.add_row("server pid", str(pid) if pid is not None else "-")
    console.print(table)
