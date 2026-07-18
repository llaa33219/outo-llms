"""`outo-llms models` - manage the model registry."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ...core import consent

console = Console()

models_app = typer.Typer(help="Manage the model registry.", no_args_is_help=True)


@models_app.command("add")
def add(
    name: str = typer.Argument(..., help="Registry name clients will use, e.g. 'tinyllama'."),
    source: str | None = typer.Option(
        None,
        "--source",
        "-s",
        help="Hugging Face repo id or path to a local .gguf file (default: the name).",
    ),
    kind: str | None = typer.Option(
        None,
        "--kind",
        "-k",
        help="'hf' or 'gguf' (default: guessed from the source).",
    ),
) -> None:
    """Register a model in the registry."""
    from ...server import db, registry

    resolved_source = source if source is not None else name
    if kind is not None:
        resolved_kind = kind
    elif resolved_source.endswith(".gguf") or Path(resolved_source).exists():
        resolved_kind = "gguf"
    else:
        resolved_kind = "hf"

    db.init_db()
    try:
        registry.add_model(name, resolved_source, resolved_kind)
    except ValueError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]model '{name}' registered[/] ({resolved_kind}: {resolved_source})")
    console.print("weights are downloaded on the first request.")


@models_app.command("list")
def list_models() -> None:
    """List registered models."""
    from ...server import db, registry

    db.init_db()
    rows = registry.list_models()
    if not rows:
        console.print("no models registered yet - add one with `outo-llms models add <name>`.")
        return
    table = Table(title="Registered models")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Source")
    table.add_column("Added")
    for row in rows:
        table.add_row(
            str(row["name"]),
            str(row["kind"]),
            str(row["source"]),
            str(row["created_at"]),
        )
    console.print(table)


@models_app.command("remove")
def remove(
    name: str = typer.Argument(..., help="Registry name of the model to remove."),
) -> None:
    """Remove a model from the registry (asks for confirmation)."""
    from ...server import db, registry

    if not consent.confirm(f"Remove model '{name}' from the registry?", default=False):
        console.print("aborted - nothing was removed.")
        return
    db.init_db()
    if registry.remove_model(name):
        console.print(f"[green]model '{name}' removed.[/]")
    else:
        console.print(f"[yellow]model '{name}' not found.[/]")
