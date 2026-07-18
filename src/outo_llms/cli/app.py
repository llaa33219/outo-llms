"""outo-llms command-line interface - the `outo-llms` command tree."""

from __future__ import annotations

import typer

from .commands import engine, models, reset, restart, setup, start, status, stop, version

app = typer.Typer(
    name="outo-llms",
    help="Deploy local LLMs behind your own managed API server.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.command("setup")(setup.setup)
app.command("reset")(reset.reset)
app.command("restart")(restart.restart)
app.command("start")(start.start)
app.command("stop")(stop.stop)
app.command("status")(status.status)
app.command("version")(version.version)

app.add_typer(models.models_app, name="models")
app.add_typer(engine.engine_app, name="engine")


def main() -> None:
    """Console-script entry point (`outo-llms`)."""
    app()


if __name__ == "__main__":
    main()
