"""`outo-llms setup` - automated, fully explicit setup wizard.

Philosophy 4 (automation): one command gets you a working deployment.
Philosophy 5 (explicitness): every action is announced, confirmed, and
logged - the system is never touched without the user's knowledge.
"""

from __future__ import annotations

import ipaddress
import os
import platform
import shutil
import socket
import sys
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from ...core import certs
from ...core import config as config_mod
from ...core import consent, paths, process

console = Console()


class EngineChoice(str, Enum):
    """Engines the wizard can install."""

    llamacpp = "llamacpp"
    vllm = "vllm"


def _prompt_engine() -> EngineChoice:
    """Ask which engine to install, defaulting to llama.cpp."""
    while True:
        answer = (
            console.input("[bold]?[/] inference engine [dim](llamacpp/vllm)[/] [llamacpp] ")
            .strip()
            .lower()
        )
        if not answer:
            return EngineChoice.llamacpp
        try:
            return EngineChoice(answer)
        except ValueError:
            console.print("[red]please enter 'llamacpp' or 'vllm'.[/]")


def _engine_requirements(engine: EngineChoice) -> str:
    """Human-readable pip requirements of an engine, for the setup plan."""
    try:
        from ...engines.base import get_adapter

        return ", ".join(get_adapter(engine.value).pip_requirements)
    except Exception:  # display-only; the install step surfaces any real adapter error
        return "the adapter's pip requirements"


def _detect_primary_ip() -> str | None:
    """Return the machine's primary IPv4 address, or None if undeterminable.

    A UDP connect only makes the kernel select an outbound interface;
    no packets are ever sent.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except OSError:
        return None


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _needs_privilege_grant(port: int) -> bool:
    return port < 1024 and os.name == "posix" and os.geteuid() != 0


def _grant_privileged_port(port: int, *, ask: bool) -> None:
    """Allow the interpreter to bind a privileged port via sudo setcap."""
    target = str(Path(sys.executable).resolve())
    consent.announce(
        "grant permission to bind privileged port",
        f"sudo setcap cap_net_bind_service=+ep on {target}",
    )
    rc = consent.run_system(
        ["sudo", "setcap", "cap_net_bind_service=+ep", target],
        reason=f"allow the server to bind privileged port {port}",
        ask=ask,
    )
    consent.log_action("setup.setcap", f"port={port} target={target} rc={rc}")
    if rc != 0:
        console.print(
            f"[yellow]the server may fail to bind port {port}; "
            "re-run with a port above 1024 or with sufficient privileges.[/]"
        )


def _open_firewall_port(port: int, *, ask: bool) -> None:
    """Open ``port``/tcp with the detected firewall tool, or explain how."""
    if platform.system() != "Linux":
        console.print(
            "[yellow]automatic firewall configuration is only supported on Linux; "
            f"open port {port}/tcp manually if needed.[/]"
        )
        return
    if shutil.which("ufw"):
        consent.run_system(
            ["ufw", "allow", f"{port}/tcp"],
            reason="open the server port in ufw",
            ask=ask,
        )
    elif shutil.which("firewall-cmd"):
        consent.run_system(
            ["firewall-cmd", "--permanent", f"--add-port={port}/tcp"],
            reason="open the server port in firewalld",
            ask=ask,
        )
        consent.run_system(
            ["firewall-cmd", "--reload"],
            reason="apply the firewalld change",
            ask=ask,
        )
    else:
        console.print(
            "[yellow]no supported firewall tool found (ufw, firewall-cmd); "
            f"open port {port}/tcp manually if needed.[/]"
        )


def setup(
    engine: EngineChoice | None = typer.Option(
        None, "--engine", "-e", help="Inference engine to install."
    ),
    host: str = typer.Option("0.0.0.0", "--host", help="Interface the API server binds to."),
    port: int = typer.Option(443, "--port", "-p", help="Port the API server listens on."),
    https: bool | None = typer.Option(
        None, "--https/--no-https", help="Serve the API over self-signed HTTPS."
    ),
    domain: str | None = typer.Option(
        None, "--domain", help="Domain or IP for the HTTPS certificate."
    ),
    open_port: bool | None = typer.Option(
        None, "--open-port/--no-open-port", help="Open the server port in the system firewall."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Non-interactive: accept all defaults, never prompt."
    ),
) -> None:
    """Run the automated, fully explicit setup wizard."""
    if config_mod.config_exists():
        reconfigure = not yes and consent.confirm(
            "outo-llms is already configured. Reconfigure?", default=False
        )
        if not reconfigure:
            console.print("setup aborted - existing configuration kept.")
            return

    if engine is None:
        engine = EngineChoice.llamacpp if yes else _prompt_engine()
    if https is None:
        https = True if yes else consent.confirm(
            "Serve the API over HTTPS with a self-signed certificate?", default=True
        )
    if open_port is None:
        open_port = True if yes else consent.confirm(
            "Open the server port in the system firewall?", default=True
        )

    domain_value = ""
    if https:
        if domain is not None:
            domain_value = domain
        else:
            default_domain = _detect_primary_ip() or "localhost"
            if yes:
                domain_value = default_domain
            else:
                answer = console.input(
                    f"[bold]?[/] domain or IP for the HTTPS certificate [{default_domain}] "
                ).strip()
                domain_value = answer or default_domain

    plan = [
        f"1. Create directories under {paths.data_dir()} and {paths.config_dir()}",
        f"2. Write configuration ({host}:{port}, https={https}, "
        f"domain={domain_value or '-'}) to {paths.config_file()}",
        f"3. Initialize the local database at {paths.db_path()}",
        f"4. Create an isolated virtualenv for engine '{engine.value}' "
        f"and pip install {_engine_requirements(engine)}",
    ]
    step = 5
    if https:
        plan.append(
            f"{step}. Generate a self-signed certificate for {domain_value} "
            f"under {paths.certs_dir()}"
        )
        step += 1
    if _needs_privilege_grant(port):
        plan.append(
            f"{step}. Grant permission to bind privileged port {port} "
            f"(sudo setcap cap_net_bind_service=+ep on {Path(sys.executable).resolve()})"
        )
        step += 1
    if open_port:
        plan.append(f"{step}. Open firewall port {port}/tcp with the detected firewall tool")
        step += 1
    plan.append(f"{step}. Start the outo-llms server in the background")
    plan.append("")
    plan.append(f"Every action is logged to {paths.action_log()}.")
    console.print(Panel("\n".join(plan), title="Setup plan"))

    if not yes and not consent.confirm("Proceed with this plan?", default=True):
        console.print("setup aborted - nothing was changed.")
        return

    try:
        consent.announce("create directories", f"{paths.data_dir()} and {paths.config_dir()}")
        paths.ensure_dirs()
        consent.log_action("setup.ensure_dirs", f"{paths.data_dir()}, {paths.config_dir()}")

        cfg = config_mod.Config(
            server=config_mod.ServerConfig(host=host, port=port, https=https, domain=domain_value),
            engine=config_mod.EngineConfig(name=engine.value),
        )
        consent.announce("write configuration", str(paths.config_file()))
        config_mod.save_config(cfg)
        consent.log_action(
            "setup.save_config",
            f"{host}:{port} https={https} domain={domain_value or '-'} engine={engine.value}",
        )

        consent.announce("initialize database", str(paths.db_path()))
        from ...server.db import init_db

        init_db()
        consent.log_action("setup.init_db", str(paths.db_path()))

        from ...engines.manager import EngineManager

        consent.announce(f"install engine '{engine.value}'", "isolated virtualenv + pip install")
        EngineManager().install(
            engine.value,
            on_event=lambda line: console.print(line, highlight=False, markup=False),
        )
        consent.log_action("setup.install_engine", engine.value)

        if https:
            consent.announce(
                "generate HTTPS certificate", f"{domain_value} under {paths.certs_dir()}"
            )
            extras = (
                [ip]
                if not _is_ip_address(domain_value) and (ip := _detect_primary_ip()) is not None
                else []
            )
            cert_path, key_path = certs.ensure_self_signed_cert(domain_value, extra_names=extras)
            consent.log_action("setup.https_cert", f"cert={cert_path} key={key_path}")

        if _needs_privilege_grant(port):
            _grant_privileged_port(port, ask=not yes)

        if open_port:
            _open_firewall_port(port, ask=not yes)

        consent.announce("start outo-llms server", f"{host}:{port}")
        process.start_server()
        consent.log_action("setup.start_server", f"{host}:{port}")
    except (RuntimeError, ValueError) as exc:
        console.print(Panel(str(exc), title="[bold red]Setup failed", border_style="red"))
        raise typer.Exit(1) from exc

    scheme = "https" if https else "http"
    display_host = domain_value if domain_value else host
    default_port = 443 if https else 80
    base_url = (
        f"{scheme}://{display_host}"
        if port == default_port
        else f"{scheme}://{display_host}:{port}"
    )
    curl_flags = "-k " if https else ""
    https_note = (
        "[yellow]self-signed certificate - browsers will ask you to confirm "
        "the exception, and curl needs -k.[/]\n"
        if https
        else ""
    )
    summary = (
        f"[bold]Base URL:[/]   {base_url}\n"
        f"[bold]API docs:[/]   {base_url}/docs\n"
        f"[bold]Action log:[/] {paths.action_log()}\n"
        f"{https_note}"
        "\n"
        "[bold]Next steps[/]\n"
        "1. Create an account (prints an API key):\n"
        f"   curl -s {curl_flags}-X POST {base_url}/v1/account/signup \\\n"
        "     -H 'Content-Type: application/json' \\\n"
        '     -d \'{"username": "me"}\'\n'
        "2. Register a model:\n"
        "   outo-llms models add <name>"
    )
    console.print(Panel(summary, title="Setup complete", border_style="green"))
