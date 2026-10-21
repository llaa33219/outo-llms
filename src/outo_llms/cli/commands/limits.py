"""`outo-llms limits` - manage token limits on API keys and workspaces.

Limits are token budgets per period (all-time ``total``, UTC calendar
``monthly``, ISO ``weekly``, rolling ``five_hour``); an unset period is
unlimited. The API server enforces them with 429 errors
before forwarding inference requests.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ...server import accounts, db

console = Console()

limits_app = typer.Typer(
    help="Manage token limits on API keys and workspaces.", no_args_is_help=True
)

_PERIOD_NAMES = ("total", "monthly", "weekly", "five_hour")


def _resolve_workspace(ref: str) -> accounts.WorkspaceDict:
    """Resolve a ``user/workspace`` reference to its workspace row."""
    username, sep, name = ref.partition("/")
    if not sep or not username or not name:
        console.print(
            "[bold red]error:[/] workspace must be given as '<username>/<workspace>'."
        )
        raise typer.Exit(1)
    db.init_db()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT w.id, w.name, w.created_at,"
            " w.limit_total, w.limit_monthly, w.limit_weekly, w.limit_5h"
            " FROM workspaces w JOIN users u ON u.id = w.user_id"
            " WHERE u.username = ? AND w.name = ?",
            (username, name),
        ).fetchone()
    if row is None:
        console.print(f"[bold red]error:[/] workspace '{ref}' not found.")
        raise typer.Exit(1)
    return accounts.WorkspaceDict(
        id=int(row["id"]),
        name=row["name"],
        created_at=row["created_at"],
        limits=accounts.LimitsDict(
            total=row["limit_total"],
            monthly=row["limit_monthly"],
            weekly=row["limit_weekly"],
            five_hour=row["limit_5h"],
        ),
    )


def _parse_updates(sets: list[str], clears: list[str]) -> dict[str, int | None]:
    """Turn ``--set period=N`` / ``--clear period`` into a limit update map."""
    updates: dict[str, int | None] = {}
    for item in sets:
        name, sep, value = item.partition("=")
        if not sep or name not in _PERIOD_NAMES:
            console.print(
                f"[bold red]error:[/] invalid --set {item!r}; expected "
                f"one of {', '.join(_PERIOD_NAMES)} with '=N' (e.g. total=100000)."
            )
            raise typer.Exit(1)
        try:
            tokens = int(value)
        except ValueError:
            console.print(f"[bold red]error:[/] --set {item!r}: {value!r} is not an integer.")
            raise typer.Exit(1) from None
        if tokens < 1:
            console.print(f"[bold red]error:[/] --set {item!r}: the limit must be >= 1.")
            raise typer.Exit(1)
        updates[name] = tokens
    for name in clears:
        if name not in _PERIOD_NAMES:
            console.print(
                f"[bold red]error:[/] invalid --clear {name!r}; "
                f"choose from {', '.join(_PERIOD_NAMES)}."
            )
            raise typer.Exit(1)
        updates[name] = None
    return updates


def _print_limits(title: str, limits: accounts.LimitsDict) -> None:
    table = Table(title=title)
    table.add_column("Period")
    table.add_column("Limit (tokens)")
    for period in _PERIOD_NAMES:
        value = limits[period]
        table.add_row(period, "-" if value is None else str(value))
    console.print(table)


@limits_app.command("key")
def key_limits(
    workspace: str = typer.Argument(..., help="Workspace as '<username>/<workspace>'."),
    key_id: int = typer.Argument(..., help="Id of the API key (see the web GUI or API)."),
    sets: list[str] = typer.Option(
        [], "--set", help="Set a limit: '--set total=100000' (repeatable)."
    ),
    clears: list[str] = typer.Option(
        [], "--clear", help="Clear a limit period (repeatable)."
    ),
) -> None:
    """Show or update the token limits of one API key."""
    ws = _resolve_workspace(workspace)
    updates = _parse_updates(sets, clears)
    if updates:
        if not accounts.set_key_limits(key_id, ws["id"], updates):
            console.print(
                f"[bold red]error:[/] key {key_id} not found in workspace '{workspace}'."
            )
            raise typer.Exit(1)
        console.print(f"[green]key {key_id} limits updated.[/]")
    for key in accounts.list_keys(ws["id"]):
        if key["id"] == key_id:
            _print_limits(f"key {key_id} ({key['label'] or 'no label'})", key["limits"])
            return
    console.print(f"[bold red]error:[/] key {key_id} not found in workspace '{workspace}'.")
    raise typer.Exit(1)


@limits_app.command("workspace")
def workspace_limits(
    workspace: str = typer.Argument(..., help="Workspace as '<username>/<workspace>'."),
    sets: list[str] = typer.Option(
        [], "--set", help="Set a limit: '--set monthly=1000000' (repeatable)."
    ),
    clears: list[str] = typer.Option(
        [], "--clear", help="Clear a limit period (repeatable)."
    ),
) -> None:
    """Show or update the total token limits of one workspace."""
    ws = _resolve_workspace(workspace)
    updates = _parse_updates(sets, clears)
    if updates:
        accounts.set_workspace_limits(ws["id"], updates)
        console.print(f"[green]workspace '{workspace}' limits updated.[/]")
        ws = _resolve_workspace(workspace)
    _print_limits(f"workspace '{workspace}'", ws["limits"])
