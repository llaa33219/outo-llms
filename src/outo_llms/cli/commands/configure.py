"""`outo-llms configure` - change server settings without a full setup.

`setup` installs an engine and initializes a fresh deployment, so changing
one setting on an existing deployment would mean `reset` (which wipes
accounts and models). `configure` instead merges changes into the existing
config: engine settings, the database, registered models, and accounts are
untouched. Every change is announced and logged; a restart is required for
the running server to pick it up.
"""

from __future__ import annotations

import ipaddress
import re

import typer
from rich.console import Console
from rich.table import Table

from ...core import certs
from ...core import config as config_mod
from ...core import consent, paths, process

console = Console()

configure_app = typer.Typer(help="Change settings of an existing deployment.", no_args_is_help=True)

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def _valid_cert_name(value: str) -> bool:
    """IP address, 'localhost', or a dotted hostname (mirrors setup)."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    if value != "localhost" and "." not in value:
        return False
    return bool(_HOSTNAME_RE.match(value))


def _show_config(cfg: config_mod.Config) -> Table:
    table = Table(title="Server configuration")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("host", cfg.server.host)
    table.add_row("port", str(cfg.server.port))
    table.add_row("https", "yes" if cfg.server.https else "no")
    table.add_row("domain", cfg.server.domain or "-")
    table.add_row("engine", cfg.engine.name)
    table.add_row("config file", str(paths.config_file()))
    return table


@configure_app.command("server")
def server(
    host: str | None = typer.Option(
        None, "--host", help="Interface the API server binds to."
    ),
    port: int | None = typer.Option(
        None, "--port", "-p", help="Port the API server listens on."
    ),
    https: bool | None = typer.Option(
        None, "--https/--no-https", help="Serve the API over HTTPS."
    ),
    domain: str | None = typer.Option(
        None, "--domain", help="Domain or IP for the HTTPS certificate."
    ),
    restart: bool = typer.Option(
        False, "--restart", help="Restart the server after applying the change."
    ),
) -> None:
    """Show or change host, port, https, and domain.

    Run without options to print the current configuration. Every setting
    is optional; only the ones given are changed. Accounts, models, the
    database, and engine settings are never touched.
    """
    if not config_mod.config_exists():
        console.print(
            "[bold red]error:[/] no configuration found - run `outo-llms setup` first."
        )
        raise typer.Exit(1)

    cfg = config_mod.load_config()
    if host is None and port is None and https is None and domain is None:
        console.print(_show_config(cfg))
        return

    changes: list[str] = []
    if host is not None and host != cfg.server.host:
        changes.append(f"host: {cfg.server.host} -> {host}")
        cfg.server.host = host
    if port is not None and port != cfg.server.port:
        if not 1 <= port <= 65535:
            console.print("[bold red]error:[/] port must be between 1 and 65535.")
            raise typer.Exit(1)
        changes.append(f"port: {cfg.server.port} -> {port}")
        cfg.server.port = port
    if https is not None and https != cfg.server.https:
        changes.append(f"https: {cfg.server.https} -> {https}")
        cfg.server.https = https
    if domain is not None and domain != cfg.server.domain:
        if not _valid_cert_name(domain):
            console.print(
                f"[bold red]error:[/] '{domain}' is not a valid IP address or DNS hostname."
            )
            raise typer.Exit(1)
        changes.append(f"domain: {cfg.server.domain or '-'} -> {domain}")
        cfg.server.domain = domain

    if not changes:
        console.print("[green]nothing to change - the configuration already matches.[/]")
        return

    if cfg.server.https and not cfg.server.domain:
        console.print(
            "[bold red]error:[/] https is enabled but no domain is set - "
            "pass --domain <ip-or-hostname> together with --https."
        )
        raise typer.Exit(1)

    consent.announce("update server configuration", "; ".join(changes))
    config_mod.save_config(cfg)
    consent.log_action("configure.server", "; ".join(changes))

    cert_note = ""
    if cfg.server.https:
        try:
            cert_path, _ = certs.ensure_server_cert(cfg.server.domain)
            cert_note = f"server certificate ready for {cfg.server.domain} ({cert_path})"
        except (RuntimeError, ValueError) as exc:
            cert_note = f"[yellow]certificate not regenerated: {exc}[/]"
            console.print(cert_note)

    if restart and process.is_server_running():
        process.ensure_bind_capability(cfg.server.port, ask=True)
        try:
            process.restart_server()
        except RuntimeError as exc:
            console.print(f"[bold red]error:[/] {exc}")
            raise typer.Exit(1) from exc
        console.print(
            "[green]configuration applied and server restarted[/] - "
            "inspect it with `outo-llms status`."
        )
    elif process.is_server_running():
        console.print(
            "[yellow]configuration saved - restart the server to apply it:[/]\n"
            "  outo-llms restart"
        )
    else:
        console.print(
            "[green]configuration applied[/] - start the server with `outo-llms start`."
        )
    if cert_note:
        console.print(f"  {cert_note}")
