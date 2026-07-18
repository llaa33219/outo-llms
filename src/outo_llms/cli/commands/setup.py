"""`outo-llms setup` - automated, fully explicit setup wizard.

Philosophy 4 (automation): one command gets you a working deployment.
Philosophy 5 (explicitness): every action is announced, confirmed, and
logged - the system is never touched without the user's knowledge.
"""

from __future__ import annotations

import platform
import shutil
from enum import Enum

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
    host: str = typer.Option("127.0.0.1", "--host", help="Interface the API server binds to."),
    port: int = typer.Option(8611, "--port", "-p", help="Port the API server listens on."),
    https: bool | None = typer.Option(
        None, "--https/--no-https", help="Serve the API over self-signed HTTPS."
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
        https = False if yes else consent.confirm(
            "Serve the API over HTTPS with a self-signed certificate?", default=False
        )
    if open_port is None:
        open_port = False if yes else consent.confirm(
            "Open the server port in the system firewall?", default=False
        )

    plan = [
        f"1. Create directories under {paths.data_dir()} and {paths.config_dir()}",
        f"2. Write configuration ({host}:{port}, https={https}) to {paths.config_file()}",
        f"3. Initialize the local database at {paths.db_path()}",
        f"4. Create an isolated virtualenv for engine '{engine.value}' "
        f"and pip install {_engine_requirements(engine)}",
    ]
    step = 5
    if https:
        plan.append(f"{step}. Generate a self-signed certificate under {paths.certs_dir()}")
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
            server=config_mod.ServerConfig(host=host, port=port, https=https),
            engine=config_mod.EngineConfig(name=engine.value),
        )
        consent.announce("write configuration", str(paths.config_file()))
        config_mod.save_config(cfg)
        consent.log_action(
            "setup.save_config", f"{host}:{port} https={https} engine={engine.value}"
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
            consent.announce("generate HTTPS certificate", str(paths.certs_dir()))
            cert_path, key_path = certs.ensure_self_signed_cert(host)
            consent.log_action("setup.https_cert", f"cert={cert_path} key={key_path}")

        if open_port:
            _open_firewall_port(port, ask=not yes)

        consent.announce("start outo-llms server", f"{host}:{port}")
        process.start_server()
        consent.log_action("setup.start_server", f"{host}:{port}")
    except (RuntimeError, ValueError) as exc:
        console.print(Panel(str(exc), title="[bold red]Setup failed", border_style="red"))
        raise typer.Exit(1) from exc

    scheme = "https" if https else "http"
    base_url = f"{scheme}://{host}:{port}"
    summary = (
        f"[bold]Base URL:[/]   {base_url}\n"
        f"[bold]API docs:[/]   {base_url}/docs\n"
        f"[bold]Action log:[/] {paths.action_log()}\n"
        "\n"
        "[bold]Next steps[/]\n"
        "1. Create an account (prints an API key):\n"
        f"   curl -s -X POST {base_url}/v1/account/signup \\\n"
        "     -H 'Content-Type: application/json' \\\n"
        '     -d \'{"username": "me"}\'\n'
        "2. Register a model:\n"
        "   outo-llms models add <name>"
    )
    console.print(Panel(summary, title="Setup complete", border_style="green"))
