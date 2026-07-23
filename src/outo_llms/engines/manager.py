"""Engine lifecycle manager.

Owns everything about an engine's presence on the machine:

- each engine gets an isolated virtualenv at ``engines_dir()/<name>/venv``;
  installs go only into that venv, never into the system interpreter;
- running engines are tracked by state files directly under
  ``engines_dir()``: ``<name>.pid``, ``<name>.port`` and ``<name>.model``;
- engines always bind 127.0.0.1 - engine ports are internal only, exposed
  to clients exclusively through the outo-llms API server;
- every action is announced (:func:`consent.announce`) and logged
  (:func:`consent.log_action`) - nothing happens silently.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import socket
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import httpx

from ..core import config as config_mod
from ..core import consent, paths, process
from .base import EngineAdapter, ModelRef, adapter_names, get_adapter

_PIP_TAIL_LINES = 20

_LIST_GGUF_SNIPPET = """\
import sys

from huggingface_hub import list_repo_files

for path in list_repo_files(sys.argv[1]):
    if path.endswith(".gguf"):
        print(path)
"""

_DOWNLOAD_SNIPPET = """\
import sys

from huggingface_hub import snapshot_download

repo_id = sys.argv[1]
allow_patterns = sys.argv[2:] if len(sys.argv) > 2 else None
local_path = snapshot_download(repo_id=repo_id, allow_patterns=allow_patterns)
print(f"weights ready at: {local_path}")
"""

_SHARD_RE = re.compile(r"^(.+)-\d{5}-of-\d{5}\.gguf$")


def _group_gguf_entries(candidates: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Collapse shard files into per-quant entries.

    Shards look like ``name-00001-of-00003.gguf``; llama.cpp loads the
    whole group from its first shard. Returns (entries, groups): entries
    are display strings (file name for standalone files, ``"<prefix> (N
    shards)"`` for groups) and groups maps each entry to its sorted
    member files.
    """
    shards: dict[str, list[str]] = {}
    groups: dict[str, list[str]] = {}
    entries: list[str] = []
    for candidate in candidates:
        match = _SHARD_RE.match(candidate)
        if match is None:
            groups[candidate] = [candidate]
            entries.append(candidate)
            continue
        shards.setdefault(match.group(1), []).append(candidate)
    for prefix in sorted(shards):
        members = sorted(shards[prefix])
        entry = f"{prefix} ({len(members)} shards)"
        groups[entry] = members
        entries.append(entry)
    return entries, groups


def _shard_members(filename: str) -> list[str]:
    """All shard files of a split GGUF, derived from the shard pattern."""
    match = re.match(r"^(.+)-(\d{5})-of-(\d{5})\.gguf$", filename)
    if match is None:
        return [filename]
    prefix, _, total = match.groups()
    return [f"{prefix}-{index:05d}-of-{total}.gguf" for index in range(1, int(total) + 1)]


def _split_progress(buffer: bytes) -> tuple[list[tuple[bytes, bytes]], bytes]:
    """Split ``buffer`` into (segment, terminator) pairs on \\r and \\n.

    Operates on bytes so tqdm's carriage returns survive; text mode would
    translate them to \\n before we could see them.
    """
    parts: list[tuple[bytes, bytes]] = []
    start = 0
    for index, byte in enumerate(buffer):
        if byte in (0x0D, 0x0A):
            parts.append((buffer[start:index], buffer[index : index + 1]))
            start = index + 1
    return parts, buffer[start:]


class EngineNotInstalledError(RuntimeError):
    """The active engine has no installed venv to download with."""


class KindMismatchError(RuntimeError):
    """The active engine cannot serve the model's kind."""

    def __init__(self, engine: str, kinds: list[str], model_kind: str) -> None:
        self.engine = engine
        self.kinds = kinds
        self.model_kind = model_kind
        super().__init__(
            f"engine '{engine}' only serves {'/'.join(kinds)} models "
            f"(this model is '{model_kind}')"
        )


def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/v1"


def _log_tail(path: Path, *, lines: int = 15) -> str:
    """Last ``lines`` of an engine log, for startup-failure messages."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "<log unavailable>"
    return "\n".join(content[-lines:]) or "<log empty>"


def _adapter_kinds(adapter: EngineAdapter) -> list[str]:
    """Model kinds ``adapter`` can serve, probed against the contract."""
    return [
        kind
        for kind in ("hf", "gguf")
        if adapter.supports(ModelRef(name="", source="", kind=kind))
    ]


class EngineManager:
    """Installs, selects, launches and stops inference engines."""

    def __init__(self) -> None:
        """Stateless: all state lives on disk (config + engines_dir())."""

    # -- inspection ------------------------------------------------------

    def available(self) -> list[str]:
        """Names of every registered engine adapter."""
        return adapter_names()

    def current_name(self) -> str:
        """Engine name from the config (defaults to ``llamacpp``)."""
        return config_mod.load_config().engine.name

    def is_installed(self, name: str | None = None) -> bool:
        """True when the marker file and the venv python both exist."""
        engine = self.current_name() if name is None else name
        return self._marker(engine).is_file() and self.venv_python(engine).is_file()

    def venv_python(self, name: str) -> Path:
        """Interpreter path inside the engine's venv (may not exist yet)."""
        venv_dir = self._engine_dir(name) / "venv"
        unix_python = venv_dir / "bin" / "python"
        if unix_python.exists():
            return unix_python
        return venv_dir / "Scripts" / "python.exe"

    def current_model(self) -> str | None:
        """Registry name of the running model, or None if nothing runs."""
        name = self.current_name()
        if self._live_pid(name) is None:
            return None
        return self._read_model(name)

    def status(self) -> dict[str, str | bool | int | None]:
        """Snapshot of the current engine: installed/running/pid/model/port."""
        name = self.current_name()
        pid = self._live_pid(name)
        port = self._read_port(name) if pid is not None else None
        return {
            "engine": name,
            "installed": self.is_installed(name),
            "running": pid is not None,
            "pid": pid,
            "model": self.current_model(),
            "port": port,
            "base_url": _base_url(port) if port is not None else None,
        }

    # -- install / select ------------------------------------------------

    def install(
        self, name: str, *, on_event: Callable[[str], None] | None = None
    ) -> None:
        """Create the engine venv and pip-install the adapter requirements.

        Every pip line is forwarded to ``on_event`` (when given). Raises
        ValueError for unknown engines and RuntimeError when pip fails.
        """
        adapter = get_adapter(name)
        engine_dir = self._engine_dir(name)
        venv_dir = engine_dir / "venv"
        paths.ensure_dirs()
        engine_dir.mkdir(parents=True, exist_ok=True)

        consent.announce(f"create virtualenv for {adapter.display_name}", str(venv_dir))
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

        python = self.venv_python(name)
        consent.announce("upgrade pip in the engine virtualenv", name)
        self._run_pip([str(python), "-m", "pip", "install", "--upgrade", "pip"], on_event)

        requirements = ", ".join(adapter.pip_requirements)
        consent.announce(f"install {adapter.display_name} into the venv", requirements)
        self._run_pip([str(python), "-m", "pip", "install", *adapter.pip_requirements], on_event)

        timestamp = dt.datetime.now().isoformat(timespec="seconds")
        self._marker(name).write_text(f"{timestamp}\n", encoding="utf-8")
        consent.log_action("install_engine", name)

    def use(self, name: str) -> None:
        """Select ``name`` as the current engine (must be installed)."""
        get_adapter(name)
        if not self.is_installed(name):
            raise RuntimeError(
                f"engine '{name}' is not installed; run `outo-llms engine install {name}`"
            )
        cfg = config_mod.load_config()
        cfg.engine.name = name
        config_mod.save_config(cfg)
        consent.log_action("use_engine", name)

    # -- run / stop ------------------------------------------------------

    def ensure_running(self, model: ModelRef, *, startup_timeout: float = 900.0) -> str:
        """Guarantee the current engine serves ``model``; return the base URL.

        Restarts the engine when a different model (or a stale process) is
        recorded. Raises RuntimeError/ValueError on setup mismatches and
        RuntimeError when the engine fails to become ready.
        """
        name = self.current_name()
        adapter = get_adapter(name)
        if not self.is_installed(name):
            raise RuntimeError(
                f"engine '{name}' is not installed; run `outo-llms engine install {name}`"
            )
        if not adapter.supports(model):
            raise ValueError(
                f"engine '{name}' cannot serve model '{model.name}' "
                f"(kind {model.kind!r}, source {model.source!r})"
            )
        pid = self._live_pid(name)
        port = self._read_port(name)
        if pid is not None and port is not None and self._read_model(name) == model.name:
            return _base_url(port)

        self.stop()

        model = self._resolve_serve_model(self.venv_python(name), model)
        cfg = config_mod.load_config()
        port = self._free_port(adapter.default_port)
        log_path = paths.logs_dir() / f"engine-{name}.log"
        paths.ensure_dirs()
        argv = adapter.serve_argv(self.venv_python(name), model, port, cfg.engine.extra_args)
        consent.announce(f"start {adapter.display_name}", f"{model.name} on 127.0.0.1:{port}")
        consent.log_action("start_engine", f"{name}: {model.name} on 127.0.0.1:{port}")

        log_handle = log_path.open("a", encoding="utf-8")
        proc = subprocess.Popen(
            argv,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        process.write_pid(self._pid_path(name), proc.pid)
        self._port_path(name).write_text(f"{port}\n", encoding="utf-8")
        self._model_path(name).write_text(f"{model.name}\n", encoding="utf-8")

        base_url = _base_url(port)
        deadline = time.monotonic() + startup_timeout
        while True:
            returncode = proc.poll()
            if returncode is not None:
                raise RuntimeError(
                    f"engine '{name}' exited during startup (code {returncode}); "
                    f"last log lines:\n{_log_tail(log_path)}"
                )
            try:
                response = httpx.get(f"{base_url}/models", timeout=0.5)
                if response.status_code == 200:
                    return base_url
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"engine '{name}' did not become ready within "
                    f"{startup_timeout:.0f}s; see log: {log_path}"
                )
            time.sleep(1.0)

    def _resolve_serve_model(self, python: Path, model: ModelRef) -> ModelRef:
        """Resolve a HF-hosted GGUF source to its cached local file.

        ``llama_cpp.server`` requires ``--model <path>``; HF sources are
        served from the local cache (``models add``/``models download``
        normally fetched them already). Other kinds and local paths pass
        through unchanged.
        """
        if model.kind != "gguf" or Path(model.source).exists():
            return model
        if ":" in model.source:
            repo, filename = model.source.split(":", 1)
            members = _shard_members(filename)
        else:
            repo = model.source
            candidates = self._list_gguf_files(python, model.source)
            if len(candidates) > 1:
                standalone = [
                    candidate
                    for candidate in candidates
                    if "mmproj" not in candidate.lower()
                ]
                if standalone:
                    candidates = standalone
            entries, groups = _group_gguf_entries(candidates)
            if len(entries) == 1:
                members = groups[entries[0]]
            else:
                listing = "\n".join(f"  - {e}" for e in entries)
                raise RuntimeError(
                    f"repo {model.source!r} contains multiple .gguf options:\n"
                    f"{listing}\nre-register with an exact file: "
                    f"outo-llms models remove {model.name} && "
                    f"outo-llms models add {model.name} -k gguf "
                    f"-s {model.source}:<file>"
                )
        first = members[0]
        lines = self._run_hf_snippet(
            [str(python), "-c", _DOWNLOAD_SNIPPET, repo, *members],
            None,
            label="resolve model files",
        )
        snapshot_dir = ""
        for line in reversed(lines):
            if line.startswith("weights ready at:"):
                snapshot_dir = line.split(":", 1)[1].strip()
                break
        if not snapshot_dir:
            raise RuntimeError(f"could not resolve local files for {repo}")
        return ModelRef(name=model.name, source=f"{snapshot_dir}/{first}", kind=model.kind)

    def stop(self) -> None:
        """Stop the current engine (if running) and clear its state files."""
        name = self.current_name()
        pid = process.read_pid(self._pid_path(name))
        if pid is not None and process.pid_alive(pid):
            consent.announce(f"stop engine '{name}'", f"pid {pid}")
            process.kill_pid(pid)
        process.remove_pid(self._pid_path(name))
        self._port_path(name).unlink(missing_ok=True)
        self._model_path(name).unlink(missing_ok=True)
        consent.log_action("stop_engine", name)

    # -- download ----------------------------------------------------------

    def download_model(
        self,
        model: ModelRef,
        *,
        on_event: Callable[[str], None] | None = None,
        choose: Callable[[list[str]], str | None] | None = None,
    ) -> str:
        """Download ``model``'s weights into the shared Hugging Face cache.

        Uses the ``huggingface_hub`` package already present in the active
        engine's venv - nothing is installed. Local-path sources need no
        download. ``on_event`` receives every output line of the download
        (tqdm progress included); ``choose`` picks one file when a bare
        GGUF repo offers several, and returning None cancels.

        Raises EngineNotInstalledError when the active engine is missing,
        KindMismatchError when it cannot serve ``model.kind``, and
        RuntimeError when listing or downloading fails.

        Returns the resolved target: ``repo:file`` when a GGUF file was
        selected, otherwise the source unchanged.
        """
        name = self.current_name()
        adapter = get_adapter(name)
        if not self.is_installed(name):
            raise EngineNotInstalledError(
                f"engine '{name}' is not installed; run `outo-llms engine install {name}`"
            )
        if not adapter.supports(model):
            raise KindMismatchError(name, _adapter_kinds(adapter), model.kind)
        if Path(model.source).exists():
            consent.log_action("download_model", "local path, skipped")
            return model.source

        python = self.venv_python(name)
        repo = model.source
        filename: str | None = None
        members: list[str] = []
        if model.kind == "gguf":
            if ":" in model.source:
                repo, filename = model.source.split(":", 1)
                members = _shard_members(filename)
            else:
                consent.announce("list .gguf files in the repo", model.source)
                candidates = self._list_gguf_files(python, model.source)
                if not candidates:
                    raise RuntimeError(f"no .gguf files in repo {model.source!r}")
                if len(candidates) > 1:
                    standalone = [
                        candidate
                        for candidate in candidates
                        if "mmproj" not in candidate.lower()
                    ]
                    if standalone:
                        candidates = standalone
                entries, groups = _group_gguf_entries(candidates)
                if len(entries) == 1:
                    entry = entries[0]
                else:
                    if choose is None:
                        listing = "\n".join(f"  - {e}" for e in entries)
                        raise RuntimeError(
                            f"repo {model.source!r} contains multiple .gguf options:\n"
                            f"{listing}\nre-run interactively or use --source repo:file"
                        )
                    chosen = choose(entries)
                    if chosen is None:
                        raise RuntimeError("download cancelled")
                    entry = chosen
                members = groups[entry]
                filename = members[0]

        target = f"{repo}:{filename}" if filename is not None else repo
        consent.announce(f"download '{model.name}' with {adapter.display_name}", target)
        argv = [str(python), "-c", _DOWNLOAD_SNIPPET, repo]
        if filename is not None:
            argv.extend(members)
        self._run_hf_snippet(argv, on_event, label="model download")
        consent.log_action("download_model", f"{name}:{model.source}")
        return target

    # -- internals -------------------------------------------------------

    @staticmethod
    def _engine_dir(name: str) -> Path:
        return paths.engines_dir() / name

    @staticmethod
    def _marker(name: str) -> Path:
        return paths.engines_dir() / name / "INSTALLED"

    @staticmethod
    def _pid_path(name: str) -> Path:
        return paths.engines_dir() / f"{name}.pid"

    @staticmethod
    def _port_path(name: str) -> Path:
        return paths.engines_dir() / f"{name}.port"

    @staticmethod
    def _model_path(name: str) -> Path:
        return paths.engines_dir() / f"{name}.model"

    def _live_pid(self, name: str) -> int | None:
        pid = process.read_pid(self._pid_path(name))
        if pid is None or not process.pid_alive(pid):
            return None
        return pid

    def _read_port(self, name: str) -> int | None:
        try:
            return int(self._port_path(name).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _read_model(self, name: str) -> str | None:
        try:
            text = self._model_path(name).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    @staticmethod
    def _free_port(preferred: int) -> int:
        """First port >= ``preferred`` with nothing listening on 127.0.0.1."""
        port = preferred
        while True:
            with socket.socket() as sock:
                sock.settimeout(0.5)
                if sock.connect_ex(("127.0.0.1", port)) != 0:
                    return port
            port += 1

    @staticmethod
    def _served_kinds(adapter: EngineAdapter) -> str:
        """Human-readable list of the model kinds ``adapter`` can serve."""
        kinds = _adapter_kinds(adapter)
        return " or ".join(kinds) if kinds else "no"

    def _list_gguf_files(self, python: Path, repo: str) -> list[str]:
        """Every ``*.gguf`` filename in HF repo ``repo``, via the venv python."""
        lines = self._run_hf_snippet(
            [str(python), "-c", _LIST_GGUF_SNIPPET, repo],
            None,
            label="list repo files",
        )
        return [line for line in lines if line.endswith(".gguf")]

    def _run_hf_snippet(
        self,
        argv: list[str],
        on_event: Callable[[str], None] | None,
        *,
        label: str,
    ) -> list[str]:
        """Run a huggingface_hub snippet, healing a missing module once.

        Engine venvs created before huggingface-hub became a requirement
        lack it; in that case install it into the venv and retry once.
        """
        try:
            return self._run_streaming(argv, on_event, env=os.environ.copy(), label=label)
        except RuntimeError as exc:
            if "No module named 'huggingface_hub'" not in str(exc):
                raise
        consent.announce(
            "install huggingface-hub into the engine venv",
            "required for downloads; missing from this venv",
        )
        self._run_pip(
            [argv[0], "-m", "pip", "install", "huggingface-hub>=0.24"], on_event
        )
        consent.log_action("install_hf_hub", argv[0])
        return self._run_streaming(argv, on_event, env=os.environ.copy(), label=label)

    @staticmethod
    def _run_streaming(
        argv: list[str],
        on_event: Callable[[str], None] | None,
        *,
        env: dict[str, str] | None = None,
        label: str,
    ) -> list[str]:
        """Run ``argv``, forwarding each output line to ``on_event``.

        stderr is merged into stdout. Returns every output line; raises
        RuntimeError with the output tail on a non-zero exit.
        """
        lines: list[str] = []
        tail: deque[str] = deque(maxlen=_PIP_TAIL_LINES)
        with subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
        ) as proc:
            assert proc.stdout is not None  # guaranteed by stdout=PIPE
            buffer = b""
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                parts, buffer = _split_progress(buffer)
                for segment, terminator in parts:
                    if not segment.strip():
                        continue
                    text = segment.decode("utf-8", errors="replace")
                    if terminator == b"\r":
                        # tqdm-style in-place update: forward marked with \r so
                        # the CLI can redraw one line instead of scrolling.
                        if on_event is not None:
                            on_event("\r" + text)
                    else:
                        lines.append(text)
                        tail.append(text)
                        if on_event is not None:
                            on_event(text)
            if buffer.strip():
                text = buffer.decode("utf-8", errors="replace")
                lines.append(text)
                tail.append(text)
                if on_event is not None:
                    on_event(text)
            returncode = proc.wait()
        if returncode != 0:
            raise RuntimeError(
                f"{label} failed (exit {returncode}); last output:\n"
                + "\n".join(tail)
            )
        return lines

    @staticmethod
    def _run_pip(argv: list[str], on_event: Callable[[str], None] | None) -> None:
        """Stream a pip invocation, forwarding each line to ``on_event``."""
        EngineManager._run_streaming(argv, on_event, label="pip install")
