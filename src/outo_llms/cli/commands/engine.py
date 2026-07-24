"""`outo-llms engine` - manage inference engines."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from ...core import consent, process

if TYPE_CHECKING:
    from ...engines.manager import EngineManager

console = Console()

engine_app = typer.Typer(help="Manage inference engines.", no_args_is_help=True)


class BackendChoice(str, Enum):
    """GPU backends llama.cpp can be built with (cpu = no acceleration)."""

    vulkan = "vulkan"
    cuda = "cuda"
    rocm = "rocm"
    cpu = "cpu"


def _manager() -> EngineManager:
    """Build the engine manager lazily so the CLI stays importable standalone."""
    from ...engines.manager import EngineManager

    return EngineManager()


@engine_app.command("list")
def list_engines() -> None:
    """List known engines, their installed state, and the active one."""
    manager = _manager()
    active = manager.current_name()
    table = Table(title="Engines")
    table.add_column("Engine")
    table.add_column("Installed")
    table.add_column("Active")
    for name in manager.available():
        table.add_row(
            name,
            "yes" if manager.is_installed(name) else "no",
            "yes" if name == active else "",
        )
    console.print(table)


@engine_app.command("use")
def use(
    name: str = typer.Argument(..., help="Engine to make active (llamacpp or vllm)."),
) -> None:
    """Select the active engine."""
    try:
        _manager().use(name)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]active engine: {name}[/]")


@engine_app.command("install")
def install(
    name: str | None = typer.Argument(None, help="Engine to install (default: the active engine)."),
) -> None:
    """Install an engine into its own isolated virtualenv."""
    manager = _manager()
    target = name if name is not None else manager.current_name()
    try:
        manager.install(
            target,
            on_event=lambda line: console.print(line, highlight=False, markup=False),
        )
    except (RuntimeError, ValueError) as exc:
        if not _offer_backend_deps(exc, manager, target):
            console.print(f"[bold red]error:[/] {exc}")
            raise typer.Exit(1) from exc
    console.print(f"[green]engine '{target}' installed.[/]")


_PM_DETECT: list[tuple[str, str]] = [
    ("apt", "apt-get"),
    ("dnf", "dnf"),
    ("pacman", "pacman"),
    ("xbps", "xbps-install"),
    ("apk", "apk"),
]

_PM_COMMANDS: dict[str, list[str]] = {
    "apt": ["apt-get", "install", "-y"],
    "dnf": ["dnf", "install", "-y"],
    "pacman": ["pacman", "-S", "--needed", "--noconfirm"],
    "xbps": ["xbps-install", "-Sy"],
    "apk": ["apk", "add"],
}

_BACKEND_PACKAGES: dict[str, dict[str, list[str]]] = {
    "vulkan": {
        "apt": ["libvulkan-dev", "glslc", "spirv-headers"],
        "dnf": ["vulkan-headers", "vulkan-loader-devel", "glslc", "spirv-headers-devel"],
        "pacman": ["vulkan-headers", "vulkan-icd-loader", "shaderc", "spirv-headers"],
        "xbps": ["Vulkan-Headers", "vulkan-loader", "vulkan-loader-devel", "shaderc", "SPIRV-Headers"],
        "apk": ["vulkan-headers", "vulkan-loader-dev", "shaderc", "spirv-headers"],
    },
    "cuda": {
        "apt": ["nvidia-cuda-toolkit"],
        "dnf": ["cuda-toolkit"],  # needs NVIDIA's cuda-<distro>.repo configured
        "pacman": ["cuda"],
    },
    "rocm": {
        "apt": ["hipcc"],
        "dnf": ["hipcc", "rocm-hip-devel"],
        "pacman": ["rocm-hip-sdk"],
    },
}


def _detect_package_manager() -> str | None:
    """Detect the system package manager for toolchain offers."""
    import shutil

    for name, binary in _PM_DETECT:
        if shutil.which(binary) is not None:
            return name
    return None


def _offer_backend_deps(
    exc: RuntimeError | ValueError, manager: EngineManager, target: str
) -> bool:
    """Offer to install missing GPU-backend build tools, then retry once."""
    from ...engines.manager import BackendDepsError

    if not isinstance(exc, BackendDepsError):
        return False
    packages_by_pm = _BACKEND_PACKAGES.get(exc.backend, {})
    pm = _detect_package_manager()
    packages = packages_by_pm.get(pm) if pm is not None else None
    if packages is None or pm is None:
        console.print(
            f"[yellow]backend '{exc.backend}' needs build tools ({exc.tool}) "
            "but this system's package manager is unsupported or has no package "
            "for it.[/] Install the toolchain manually, or pick the CPU build "
            "with `outo-llms engine backend cpu` and re-run install."
        )
        raise typer.Exit(1) from exc
    console.print(
        f"[yellow]backend '{exc.backend}' needs build tools ({exc.tool}).[/] "
        f"They can be installed system-wide ({pm}): "
        f"sudo {' '.join(_PM_COMMANDS[pm])} {' '.join(packages)}"
    )
    if pm == "dnf" and exc.backend == "cuda":
        console.print(
            "[dim]note: cuda-toolkit requires NVIDIA's cuda-<distro>.repo to be "
            "configured first (Fedora's own repos do not ship CUDA).[/]"
        )
    rc = consent.run_system(
        ["sudo", *_PM_COMMANDS[pm], *packages],
        reason=f"install the {exc.backend} build toolchain for llama.cpp",
        ask=True,
    )
    if rc != 0:
        console.print(
            "[yellow]skipping GPU build.[/] Install the packages manually, or pick "
            "the CPU build with `outo-llms engine backend cpu` and re-run install."
        )
        raise typer.Exit(1) from exc
    console.print(f"[bold]retrying engine install with backend '{exc.backend}'...[/]")
    try:
        manager.install(
            target,
            on_event=lambda line: console.print(line, highlight=False, markup=False),
        )
    except (RuntimeError, ValueError) as retry_exc:
        console.print(f"[bold red]error:[/] {retry_exc}")
        raise typer.Exit(1) from retry_exc
    return True


@engine_app.command("backend")
def backend(
    choice: BackendChoice = typer.Argument(
        ..., help="GPU backend for llama.cpp: vulkan (default), cuda, rocm, or cpu."
    ),
) -> None:
    """Select the GPU backend; re-run `engine install llamacpp` to rebuild."""
    from ...core import config as config_mod

    manager = _manager()
    cfg = config_mod.load_config()
    if cfg.engine.backend == choice.value:
        console.print(f"[green]backend is already '{choice.value}'.[/]")
        return
    cfg.engine.backend = choice.value
    config_mod.save_config(cfg)
    consent.log_action("engine_backend", choice.value)
    manager.stop()
    console.print(f"[green]backend set to '{choice.value}'.[/]")
    if choice.value != "cpu":
        console.print(
            "re-run `outo-llms engine install llamacpp` to rebuild with "
            f"{choice.value.upper()} support (compiles from source)."
        )
    else:
        console.print(
            "re-run `outo-llms engine install llamacpp` to switch back to the "
            "fast prebuilt CPU wheel."
        )


@engine_app.command("upgrade")
def upgrade(
    name: str | None = typer.Argument(None, help="Engine to upgrade (default: the active engine)."),
) -> None:
    """Upgrade the engine's packages in place (e.g. newer model architectures)."""
    manager = _manager()
    target = name if name is not None else manager.current_name()
    try:
        manager.upgrade(
            target,
            on_event=lambda line: console.print(line, highlight=False, markup=False),
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]engine '{target}' upgraded.[/]")


@engine_app.command("reset")
def reset() -> None:
    """Force-stop engines and clear runtime state (registry/weights kept)."""
    if not consent.confirm(
        "Stop all engine processes and clear engine runtime state?", default=False
    ):
        console.print("aborted - nothing was changed.")
        return
    _manager().reset()
    console.print(
        "[green]engine state reset.[/] model registry and downloaded weights are "
        "untouched; the next request starts a fresh engine."
    )


@engine_app.command("status")
def engine_status() -> None:
    """Show the active engine's runtime status."""
    info = _manager().status()
    table = Table(title="Engine status")
    table.add_column("Property")
    table.add_column("Value")
    for key in ("engine", "backend", "installed", "running", "pid", "model", "port", "base_url"):
        value = info.get(key)
        table.add_row(key, "-" if value is None else str(value))
    pid = process.server_pid()
    table.add_row("server running", "yes" if process.is_server_running() else "no")
    table.add_row("server pid", str(pid) if pid is not None else "-")
    console.print(table)
