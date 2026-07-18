"""Explicitness machinery - philosophy 5 made code.

Every automated action outo-llms performs goes through this module:

- :func:`announce` tells the user what is about to happen.
- :func:`confirm` / :func:`confirm_twice` gate destructive or
  system-touching actions behind explicit consent.
- :func:`log_action` appends to ``logs/actions.log`` so there is always an
  auditable trail of what the tool did.
- :func:`run_system` wraps any invocation of an external system command
  (e.g. ``ufw allow``) with announcement, optional confirmation and logging.

The system is never touched without the user's knowledge.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from collections.abc import Sequence

from rich.console import Console

from . import paths

console = Console()


def announce(action: str, detail: str | None = None) -> None:
    """Tell the user about an action that is about to happen."""
    suffix = f" - {detail}" if detail else ""
    console.print(f"[bold cyan]ACTION[/] {action}{suffix}")


def confirm(question: str, *, default: bool = False) -> bool:
    """Ask a yes/no question. Any non-yes answer (or abort) means no."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = console.input(f"[bold]?[/] {question} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


def confirm_twice(first: str, second: str) -> bool:
    """Two independent confirmations, both required. Used by ``reset``."""
    return confirm(first, default=False) and confirm(second, default=False)


def log_action(action: str, detail: str = "") -> None:
    """Append an auditable record to the action log."""
    paths.ensure_dirs()
    timestamp = dt.datetime.now().isoformat(timespec="seconds")
    with paths.action_log().open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp}\t{action}\t{detail}\n")


def run_system(cmd: Sequence[str], *, reason: str, ask: bool = True) -> int:
    """Run an external system command explicitly.

    Announces the exact command and its reason, optionally asks for consent,
    logs it, then runs it without a shell. Returns the exit code, or -1 if
    the user declined.
    """
    rendered = " ".join(cmd)
    announce(f"run system command: {rendered}", reason)
    if ask and not confirm("Proceed with this system command?", default=False):
        console.print("[yellow]skipped by user[/]")
        log_action("run_system_skipped", rendered)
        return -1
    log_action("run_system", rendered)
    return subprocess.run(list(cmd), check=False).returncode
