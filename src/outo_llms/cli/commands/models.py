"""`outo-llms models` - manage the model registry."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ...core import consent

if TYPE_CHECKING:
    from ...engines.base import ModelRef
    from ...engines.manager import KindMismatchError

console = Console()

models_app = typer.Typer(help="Manage the model registry.", no_args_is_help=True)


def _print_progress(line: str) -> None:
    """Forward one download output line verbatim (no Rich markup parsing).

    Lines marked with a leading ``\\r`` are tqdm-style in-place updates
    and redraw the current terminal line instead of scrolling.
    """
    if line.startswith("\r"):
        console.print(line, end="", markup=False, highlight=False)
        return
    console.print(line, markup=False, highlight=False)


def _pick_gguf(candidates: list[str]) -> str | None:
    """Numbered interactive picker over GGUF candidates; None cancels."""
    console.print("[bold]multiple .gguf files found - pick one to download:[/]")
    for index, candidate in enumerate(candidates, start=1):
        console.print(f"  {index}. {candidate}", markup=False)
    try:
        answer = console.input("number (empty to cancel): ").strip()
    except EOFError:
        console.print()
        console.print(
            "[yellow]no interactive input;[/] re-run with `--source repo:file` "
            "to pick one of:"
        )
        for candidate in candidates:
            console.print(f"  - {candidate}", markup=False)
        return None
    except KeyboardInterrupt:
        console.print()
        return None
    if not answer:
        return None
    try:
        choice = int(answer)
    except ValueError:
        return None
    if not 1 <= choice <= len(candidates):
        return None
    return candidates[choice - 1]


def _print_kind_guidance(model: ModelRef, exc: KindMismatchError) -> None:
    """Show the exact commands that resolve an engine/kind mismatch."""
    from rich.markup import escape

    target = exc.kinds[0] if exc.kinds else "hf"
    other = "vllm" if exc.engine == "llamacpp" else "llamacpp"
    name = escape(model.name)
    source = escape(model.source)
    console.print(
        Panel(
            f"engine '{exc.engine}' serves '{target}' models only, "
            f"but '{name}' is registered as '{exc.model_kind}'.\n\n"
            f"[bold]Re-register with the right kind:[/]\n"
            f"  outo-llms models remove {name}\n"
            f"  outo-llms models add {name} -k {target} -s {source}\n\n"
            f"[bold]Or switch the engine instead:[/]\n"
            f"  outo-llms engine install {other} && outo-llms engine use {other}\n\n"
            "[bold]What the flags mean:[/]\n"
            "  -k, --kind KIND    model format: 'gguf' for llama.cpp, 'hf' for vLLM\n"
            "  -s, --source SRC   Hugging Face repo id or a local .gguf path\n"
            "                     (repo:file picks one file inside the repo)\n"
            "      --hf REPO      shortcut for HF-format models; implies -k hf (for vLLM)",
            title="kind mismatch - nothing was downloaded",
            border_style="yellow",
        )
    )


def _download_weights(name: str, *, force: bool = False) -> bool:
    """Download weights for registered model ``name`` via the active engine.

    Returns True when the weights are ready to serve. A missing engine or
    a kind mismatch is a yellow warning (returns False) - the registration
    is untouched. Real download failures print a red panel and exit 1.
    """
    from ...engines.manager import (
        EngineManager,
        EngineNotInstalledError,
        KindMismatchError,
    )
    from ...server import registry

    model = registry.get_model(name)
    if model is None:
        console.print(f"[bold red]error:[/] model '{name}' is not registered.")
        raise typer.Exit(1)

    manager = EngineManager()
    try:
        target = manager.download_model(
            model, on_event=_print_progress, choose=_pick_gguf, force=force
        )
    except EngineNotInstalledError:
        console.print(
            "[yellow]no engine installed yet;[/] weights will download on first use "
            "or via `outo-llms models download` after `outo-llms engine install`."
        )
        return False
    except KindMismatchError as exc:
        _print_kind_guidance(model, exc)
        return False
    except RuntimeError as exc:
        console.print(
            Panel(
                f"{exc}\n\nmodel '{name}' stays registered; fetch weights later with "
                f"`outo-llms models download {name}`.",
                title="download failed",
                border_style="red",
            )
        )
        raise typer.Exit(1) from exc
    if target != model.source:
        registry.update_source(name, target)
        console.print(f"[dim]registry source pinned to {target}[/]")
    return True


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
    hf: str | None = typer.Option(
        None,
        "--hf",
        help="Hugging Face repo id to install (sets source and kind=hf).",
    ),
    no_download: bool = typer.Option(
        False,
        "--no-download",
        help="Register only; download weights later via `models download`.",
    ),
) -> None:
    """Register a model, then download its weights for the active engine."""
    from ...server import db, registry

    if hf is not None:
        if source is not None or kind is not None:
            console.print("[bold red]error:[/] --hf cannot be combined with --source or --kind.")
            raise typer.Exit(1)
        resolved_source, resolved_kind = hf, "hf"
    else:
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

    if no_download:
        console.print(
            f"[green]model '{name}' registered (download skipped)[/] "
            f"({resolved_kind}: {resolved_source})"
        )
        return
    if _download_weights(name):
        console.print(
            f"[green]model '{name}' registered and downloaded[/] - ready to serve."
        )
    else:
        console.print(
            f"[green]model '{name}' registered[/] ({resolved_kind}: {resolved_source})"
        )


@models_app.command("download")
def download(
    name: str = typer.Argument(..., help="Registry name of the model to download."),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Re-download all weights, ignoring the cache (repairs corrupted downloads).",
    ),
) -> None:
    """Download a registered model's weights now (idempotent via the HF cache)."""
    from ...server import db

    db.init_db()
    if _download_weights(name, force=force):
        console.print(f"[green]model '{name}' downloaded[/] - ready to serve.")


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
