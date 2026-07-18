"""`outo-llms version` - print the installed version."""

from __future__ import annotations

from rich.console import Console

import outo_llms

console = Console()


def version() -> None:
    """Print the outo-llms version."""
    console.print(f"outo-llms {outo_llms.__version__}")
