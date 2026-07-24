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
    # kill(pid, 0) succeeds for zombies, so check the /proc state field;
    # comm may contain spaces/parens, so parse after its closing paren.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        state = stat.rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        return True
    return state != "Z"


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


def _tail(path: Path, *, lines: int = 15) -> str:
    """Last ``lines`` of a log file, for error messages."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "<log unavailable>"
    return "\n".join(content[-lines:]) or "<log empty>"


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
    import outo_llms

    paths.server_version_file().write_text(
        f"{outo_llms.__version__}\n", encoding="utf-8"
    )
    # A wildcard bind address is not connectable; probe loopback instead.
    check_host = "127.0.0.1" if cfg.server.host in ("0.0.0.0", "::") else cfg.server.host
    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if _port_open(check_host, cfg.server.port):
            return
        if proc.poll() is not None:
            remove_pid(paths.pid_file())
            raise RuntimeError(
                "server exited during startup; last log lines:\n"
                + _tail(paths.server_log())
            )
        time.sleep(0.25)
    if proc.poll() is not None:
        remove_pid(paths.pid_file())
        raise RuntimeError(
            "server exited during startup; last log lines:\n" + _tail(paths.server_log())
        )
    consent.console.print(
        f"[yellow]server still starting; check `outo-llms status` or {paths.server_log()}[/]"
    )


def server_version() -> str | None:
    """Version of the running server process, recorded at its start."""
    pid = server_pid()
    if pid is None:
        return None
    try:
        return paths.server_version_file().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def stop_server(*, timeout: float = 10.0) -> bool:
    """Stop the API server. Returns True if a process was stopped."""
    pid = read_pid(paths.pid_file())
    if pid is None:
        return False
    consent.announce("stop outo-llms server", f"pid {pid}")
    consent.log_action("stop_server", f"pid {pid}")
    stopped = kill_pid(pid, timeout=timeout)
    remove_pid(paths.pid_file())
    try:
        paths.server_version_file().unlink()
    except FileNotFoundError:
        pass
    return stopped


def restart_server() -> None:
    stop_server()
    start_server()
