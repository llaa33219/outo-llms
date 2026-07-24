"""`outo-llms engine` - manage inference engines."""

from __future__ import annotations

import re
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


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@engine_app.command("add")
def add_engine(
    engine_id: str = typer.Argument(..., help="Name for the new engine instance."),
    type: str = typer.Option(
        ..., "--type", "-t", help="Runtime family: 'llamacpp' or 'vllm'."
    ),
    source: str = typer.Option(
        "pypi",
        "--source",
        "-s",
        help="Package source: 'pypi', a git URL (…git), a wheel URL, or a local path.",
    ),
    backend: BackendChoice = typer.Option(
        BackendChoice.vulkan, "--backend", "-b", help="GPU backend (llamacpp only)."
    ),
) -> None:
    """Register a custom engine instance (e.g. a forked runtime)."""
    from ...core import config as config_mod
    from ...engines.base import get_adapter

    if not _ID_RE.match(engine_id):
        console.print(
            "[bold red]error:[/] engine id must be lowercase letters, digits, '-' or '_'."
        )
        raise typer.Exit(1)
    try:
        get_adapter(type)
    except ValueError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    cfg = config_mod.load_config()
    if engine_id in cfg.engine.engines:
        console.print(f"[bold red]error:[/] engine '{engine_id}' already exists.")
        raise typer.Exit(1)
    cfg.engine.engines[engine_id] = config_mod.EngineInstance(
        type=type, source=source, backend=backend.value
    )
    config_mod.save_config(cfg)
    consent.log_action("add_engine", f"{engine_id} type={type} source={source}")
    console.print(
        f"[green]engine '{engine_id}' added[/] (type={type}, source={source}, "
        f"backend={backend.value}). Install it with `outo-llms engine install {engine_id}`."
    )


@engine_app.command("remove")
def remove_engine(
    engine_id: str = typer.Argument(..., help="Custom engine instance to remove."),
) -> None:
    """Remove a custom engine instance (venv, state files, and registry entry)."""
    from ...core import config as config_mod

    cfg = config_mod.load_config()
    if engine_id not in cfg.engine.engines:
        console.print(
            f"[bold red]error:[/] '{engine_id}' is not a custom engine instance "
            "(built-ins llamacpp/vllm cannot be removed)."
        )
        raise typer.Exit(1)
    if cfg.engine.name == engine_id:
        console.print(
            f"[bold red]error:[/] '{engine_id}' is the active engine; "
            "switch with `outo-llms engine use` first."
        )
        raise typer.Exit(1)
    if not consent.confirm(
        f"Remove engine '{engine_id}' (its venv and runtime state)?", default=False
    ):
        console.print("aborted - nothing was changed.")
        return
    manager = _manager()
    manager.stop(engine_id)
    import shutil

    from ...core import paths

    engine_dir = paths.engines_dir() / engine_id
    if engine_dir.is_dir():
        consent.announce("remove engine virtualenv", str(engine_dir))
        shutil.rmtree(engine_dir, ignore_errors=True)
    del cfg.engine.engines[engine_id]
    config_mod.save_config(cfg)
    consent.log_action("remove_engine", engine_id)
    console.print(f"[green]engine '{engine_id}' removed.[/]")


@engine_app.command("list")
def list_engines() -> None:
    """List engine instances, their source, backend, and installed state."""
    from ...core import config as config_mod

    manager = _manager()
    cfg = config_mod.load_config()
    active = manager.current_name()
    table = Table(title="Engines")
    table.add_column("Instance")
    table.add_column("Type")
    table.add_column("Source")
    table.add_column("Backend")
    table.add_column("Installed")
    table.add_column("Active")
    for name in manager.available():
        instance = config_mod.resolve_instance(cfg, name)
        table.add_row(
            name, instance.type, instance.source, instance.backend,
            "yes" if manager.is_installed(name) else "no",
            "yes" if name == active else "",
        )
    for instance_id, instance in cfg.engine.engines.items():
        table.add_row(
            instance_id, instance.type, instance.source, instance.backend,
            "yes" if manager.is_installed(instance_id) else "no",
            "yes" if instance_id == active else "",
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
    engine_id: str | None = typer.Option(
        None, "--engine", "-e", help="Instance to change (default: the active engine)."
    ),
) -> None:
    """Select the GPU backend; re-run `engine install <id>` to rebuild."""
    from ...core import config as config_mod

    manager = _manager()
    cfg = config_mod.load_config()
    target = engine_id if engine_id is not None else manager.current_name()
    if target in cfg.engine.engines:
        if cfg.engine.engines[target].backend == choice.value:
            console.print(f"[green]backend of '{target}' is already '{choice.value}'.[/]")
            return
        cfg.engine.engines[target].backend = choice.value
    else:
        if target not in manager.available():
            console.print(f"[bold red]error:[/] unknown engine instance '{target}'.")
            raise typer.Exit(1)
        if cfg.engine.backend == choice.value:
            console.print(f"[green]backend is already '{choice.value}'.[/]")
            return
        cfg.engine.backend = choice.value
    config_mod.save_config(cfg)
    consent.log_action("engine_backend", f"{target}={choice.value}")
    manager.stop(target)
    console.print(f"[green]backend of '{target}' set to '{choice.value}'.[/]")
    console.print(
        f"re-run `outo-llms engine install {target}` to rebuild with the new backend."
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
