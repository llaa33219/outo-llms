"""`outo-llms status` - show server, engine, and path status."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from ...core import config as config_mod
from ...core import paths, process

console = Console()


def _server_table() -> Table:
    cfg = config_mod.load_config()
    scheme = "https" if cfg.server.https else "http"
    pid = process.server_pid()
    display_host = cfg.server.domain or cfg.server.host
    default_port = 443 if cfg.server.https else 80
    base_url = (
        f"{scheme}://{display_host}"
        if cfg.server.port == default_port
        else f"{scheme}://{display_host}:{cfg.server.port}"
    )
    table = Table(title="Server")
    table.add_column("Property")
    table.add_column("Value")
    table.add_row("running", "yes" if process.is_server_running() else "no")
    table.add_row("pid", str(pid) if pid is not None else "-")
    table.add_row("host", cfg.server.host)
    table.add_row("port", str(cfg.server.port))
    table.add_row("https", "yes" if cfg.server.https else "no")
    table.add_row("domain", cfg.server.domain or "-")
    table.add_row("base url", base_url)
    return table


def _paths_table() -> Table:
    table = Table(title="Paths")
    table.add_column("Name")
    table.add_column("Path")
    table.add_row("config file", str(paths.config_file()))
    table.add_row("data dir", str(paths.data_dir()))
    table.add_row("action log", str(paths.action_log()))
    table.add_row("server log", str(paths.server_log()))
    return table


def status() -> None:
    """Show server, engine, and path status."""
    console.print(_server_table())

    import outo_llms

    server_version = process.server_version()
    if server_version is not None and server_version != outo_llms.__version__:
        console.print(
            f"[bold yellow]the running server is v{server_version} but the CLI is "
            f"v{outo_llms.__version__} - run `outo-llms restart` to pick up the "
            "installed version.[/]"
        )

    try:
        from ...engines.manager import EngineManager

        info = EngineManager().status()
    except Exception as exc:  # status must never crash, even if the engine layer is broken
        console.print(f"[yellow]engine status unavailable: {exc}[/]")
    else:
        engine_table = Table(title="Engine")
        engine_table.add_column("Property")
        engine_table.add_column("Value")
        for key in ("engine", "installed", "running", "pid", "model", "port", "base_url"):
            value = info.get(key)
            engine_table.add_row(key, "-" if value is None else str(value))
        console.print(engine_table)

    console.print(_paths_table())
