"""Background server process control (start/stop/restart) via pidfiles.

The server runs detached as ``python -m outo_llms.server`` with output going
to ``logs/server.log``. The pid is tracked in ``data/server.pid``. These
helpers are also reused by the engine manager for engine subprocesses.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import config as config_mod
from . import consent, paths

_STARTUP_TIMEOUT = 15.0


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def remove_pid(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_pid(pid: int, *, timeout: float = 10.0) -> bool:
    """SIGTERM, wait up to ``timeout``, then SIGKILL. True if the process is gone."""
    if not pid_alive(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return not pid_alive(pid)


def server_pid() -> int | None:
    pid = read_pid(paths.pid_file())
    if pid is None or not pid_alive(pid):
        return None
    return pid


def is_server_running() -> bool:
    return server_pid() is not None


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def wait_for_port(host: str, port: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.25)
    return False


def start_server() -> None:
    """Start the API server detached. Raises RuntimeError if already running
    or if the process dies during startup."""
    running = server_pid()
    if running is not None:
        raise RuntimeError(f"server already running (pid {running})")
    paths.ensure_dirs()
    cfg = config_mod.load_config()
    consent.announce(
        "start outo-llms server",
        f"{cfg.server.host}:{cfg.server.port} (https={cfg.server.https})",
    )
    consent.log_action("start_server", f"{cfg.server.host}:{cfg.server.port}")
    log_handle = paths.server_log().open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "outo_llms.server"],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    write_pid(paths.pid_file(), proc.pid)
    if wait_for_port(cfg.server.host, cfg.server.port, timeout=_STARTUP_TIMEOUT):
        return
    if not pid_alive(proc.pid):
        remove_pid(paths.pid_file())
        raise RuntimeError(
            f"server exited during startup; see log: {paths.server_log()}"
        )
    consent.console.print(
        f"[yellow]server still starting; check `outo-llms status` or {paths.server_log()}[/]"
    )


def stop_server(*, timeout: float = 10.0) -> bool:
    """Stop the API server. Returns True if a process was stopped."""
    pid = read_pid(paths.pid_file())
    if pid is None:
        return False
    consent.announce("stop outo-llms server", f"pid {pid}")
    consent.log_action("stop_server", f"pid {pid}")
    stopped = kill_pid(pid, timeout=timeout)
    remove_pid(paths.pid_file())
    return stopped


def restart_server() -> None:
    stop_server()
    start_server()
