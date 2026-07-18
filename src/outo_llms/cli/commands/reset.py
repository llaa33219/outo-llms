"""`outo-llms reset` - wipe everything back to factory state."""

from __future__ import annotations

import shutil

from rich.console import Console

from ...core import consent, paths, process

console = Console()


def reset() -> None:
    """Stop everything and delete all outo-llms data (asks twice)."""
    if not consent.confirm_twice(
        "This will STOP the server and DELETE all outo-llms data "
        "(config, database, engine virtualenvs, logs). Continue?",
        f"Really delete everything under {paths.data_dir()} and {paths.config_dir()}? "
        "This cannot be undone.",
    ):
        console.print("aborted - nothing was deleted.")
        return

    process.stop_server()
    try:
        from ...engines.manager import EngineManager

        EngineManager().stop()
    except Exception as exc:  # a broken engine must never block a factory reset
        console.print(f"[yellow]warning: could not stop the engine ({exc}); continuing.[/]")

    consent.announce("delete outo-llms data", f"{paths.data_dir()} and {paths.config_dir()}")
    consent.log_action("reset", "deleted data and config directories")
    shutil.rmtree(paths.data_dir(), ignore_errors=True)
    shutil.rmtree(paths.config_dir(), ignore_errors=True)
    console.print("[green]outo-llms has been reset to factory state.[/]")
