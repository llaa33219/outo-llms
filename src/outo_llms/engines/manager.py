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
import shutil
import socket
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

import httpx

from ..core import config as config_mod
from ..core import consent, paths, process
from .base import EngineAdapter, ModelRef, adapter_names, get_adapter
from .llamacpp import LlamaCppAdapter

_PIP_TAIL_LINES = 20

_LIST_GGUF_SNIPPET = """\
import sys

from huggingface_hub import list_repo_files

for path in list_repo_files(sys.argv[1]):
    if path.endswith(".gguf"):
        print(path)
"""

_DOWNLOAD_SNIPPET = """\
import os
import sys

from huggingface_hub import snapshot_download

repo_id = sys.argv[1]
allow_patterns = sys.argv[2:] if len(sys.argv) > 2 else None
force = os.environ.get("OUTO_FORCE_DOWNLOAD") == "1"
local_path = snapshot_download(
    repo_id=repo_id, allow_patterns=allow_patterns, force_download=force
)
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


class BackendDepsError(RuntimeError):
    """Build tools for the selected GPU backend are missing."""

    def __init__(self, backend: str, tool: str) -> None:
        self.backend = backend
        self.tool = tool
        super().__init__(
            f"backend '{backend}' needs '{tool}' on PATH "
            f"(or pick another backend: outo-llms engine backend cpu)"
        )


class _BackendSpec(TypedDict):
    cmake: str
    tool: str


_BACKEND_BUILD: dict[str, _BackendSpec] = {
    "vulkan": {"cmake": "GGML_VULKAN", "tool": "glslc"},
    "cuda": {"cmake": "GGML_CUDA", "tool": "nvcc"},
    "rocm": {"cmake": "GGML_HIP", "tool": "hipcc"},
}

BACKEND_NAMES = ["vulkan", "cuda", "rocm", "cpu"]

_KNOWN_TOOL_DIRS: dict[str, list[str]] = {
    "nvcc": ["/opt/cuda/bin"],
    "hipcc": ["/opt/rocm/bin"],
}


def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/v1"


_ARCHIVE_SUFFIXES = (".whl", ".tar.gz", ".tgz", ".zip", ".tar.bz2")


def _pip_source(source: str) -> str:
    """Normalize a custom engine package source into a pip install argument."""
    if source.startswith("git+"):
        return source
    if "://" in source:
        if source.endswith(_ARCHIVE_SUFFIXES):
            return source
        return f"git+{source}"
    if Path(source).exists():
        return str(Path(source).resolve())
    raise ValueError(
        f"unrecognized engine source {source!r}; use a git URL, "
        "a package/wheel URL, or an existing local path"
    )


def _is_cmake_source(source: str) -> bool:
    """Whether the source is a llama.cpp fork to build with cmake."""
    if source.startswith("git+"):
        return True
    if "://" in source:
        return not source.endswith(_ARCHIVE_SUFFIXES)
    path = Path(source)
    return path.is_dir() and (path / "CMakeLists.txt").is_file()


def _cmake_git(source: str) -> tuple[str, str | None]:
    """Split a git source into (url, ref); ref comes from a trailing @ref."""
    url = source.removeprefix("git+")
    if "@" in url.rsplit("/", 1)[-1]:
        url, _, ref = url.rpartition("@")
        return url, ref or None
    return url, None


def _log_error_context(path: Path) -> str:
    """Error-relevant lines plus the tail of an engine log.

    Engine failures end in a Python traceback that buries the real cause
    (e.g. llama.cpp's own "error loading model" line); surface both.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "<log unavailable>"
    if not lines:
        return "<log empty>"
    interesting = [
        line
        for line in lines[-200:]
        if re.search(
            r"error|failed|unknown|invalid|magic|architecture", line, re.IGNORECASE
        )
    ]
    excerpt = interesting[-5:]
    tail = lines[-10:]
    parts: list[str] = []
    if excerpt and excerpt != tail[-len(excerpt) :]:
        parts.append("error lines:\n" + "\n".join(excerpt))
    parts.append("last log lines:\n" + "\n".join(tail))
    return "\n".join(parts)


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

    def _instance(self, name: str) -> config_mod.EngineInstance:
        """Resolve an engine instance id to its type/source/backend."""
        return config_mod.resolve_instance(config_mod.load_config(), name)

    def _adapter_for(self, name: str) -> EngineAdapter:
        """Adapter for an instance, in binary mode for llama.cpp forks."""
        from .llamacpp import LlamaCppAdapter

        instance = self._instance(name)
        if instance.type == "llamacpp" and _is_cmake_source(instance.source):
            return LlamaCppAdapter(binary=True)
        return get_adapter(instance.type)

    def _engine_for(self, model: ModelRef) -> str:
        """The instance serving ``model``: its pin, or the default engine."""
        return model.engine if model.engine else self.current_name()

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

    def loaded_at(self) -> str | None:
        """ISO-8601 UTC timestamp of when the running model was loaded.

        Derived from the mtime of the active engine's ``<name>.model``
        state file, which is written each time the engine is (re)started
        with a model. None when the engine is not running or the file is
        missing.
        """
        name = self.current_name()
        if self._live_pid(name) is None:
            return None
        try:
            mtime = self._model_path(name).stat().st_mtime
        except OSError:
            return None
        return dt.datetime.fromtimestamp(mtime, dt.timezone.utc).isoformat()

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
            "backend": config_mod.load_config().engine.backend,
        }

    # -- install / select ------------------------------------------------

    def _instance_requirements(
        self, instance: config_mod.EngineInstance, adapter: EngineAdapter
    ) -> list[str]:
        """Pip arguments that install an engine instance's runtime package."""
        if instance.source == "pypi":
            return list(adapter.pip_requirements)
        if instance.type == "llamacpp" and _is_cmake_source(instance.source):
            return ["huggingface-hub>=0.24"]
        requirement = _pip_source(instance.source)
        if instance.type == "llamacpp":
            return [requirement, "huggingface-hub>=0.24"]
        return [requirement]

    def install(
        self, name: str, *, on_event: Callable[[str], None] | None = None
    ) -> None:
        """Create the engine venv and install the instance's runtime.

        Every output line is forwarded to ``on_event`` (when given). Raises
        ValueError for unknown engines and RuntimeError when a step fails.
        """
        adapter = self._adapter_for(name)
        instance = self._instance(name)
        running = self._live_pid(name)
        if running is not None:
            consent.announce(
                f"stop running engine '{name}' before reinstall", f"pid {running}"
            )
            self.stop()
        engine_dir = self._engine_dir(name)
        venv_dir = engine_dir / "venv"
        paths.ensure_dirs()
        engine_dir.mkdir(parents=True, exist_ok=True)

        env: dict[str, str] | None = None
        is_cmake = isinstance(adapter, LlamaCppAdapter) and adapter.binary
        if instance.type == "llamacpp" and instance.backend != "cpu":
            if is_cmake:
                env = self._backend_toolchain_env(instance.backend)
            else:
                env = self._backend_env(name, adapter, instance.backend)

        consent.announce(f"create virtualenv for {adapter.display_name}", str(venv_dir))
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

        python = self.venv_python(name)
        consent.announce("upgrade pip in the engine virtualenv", name)
        self._run_pip([str(python), "-m", "pip", "install", "--upgrade", "pip"], on_event)

        requirements = self._instance_requirements(instance, adapter)
        consent.announce(
            f"install {adapter.display_name} into the venv", ", ".join(requirements)
        )
        pip_args = [str(python), "-m", "pip", "install"]
        if env is not None and not is_cmake:
            pip_args += ["--force-reinstall", "--no-cache-dir"]
        self._run_streaming(
            [*pip_args, *requirements],
            on_event,
            env=env,
            label="pip install",
        )
        if is_cmake:
            self._build_llamacpp(name, instance, env, on_event)

        timestamp = dt.datetime.now().isoformat(timespec="seconds")
        self._marker(name).write_text(f"{timestamp}\n", encoding="utf-8")
        consent.log_action("install_engine", name)

    def _build_llamacpp(
        self,
        name: str,
        instance: config_mod.EngineInstance,
        env: dict[str, str] | None,
        on_event: Callable[[str], None] | None,
    ) -> None:
        """Clone (or reuse) a llama.cpp checkout and build it with cmake."""
        for tool in ("git", "cmake"):
            if shutil.which(tool) is None:
                raise RuntimeError(
                    f"building llama.cpp from source needs '{tool}' on PATH "
                    f"(e.g. sudo apt-get install -y {tool})"
                )
        engine_dir = self._engine_dir(name)
        src_dir = engine_dir / "src"
        source = instance.source
        if "://" in source or source.startswith("git+"):
            url, ref = _cmake_git(source)
            if not src_dir.is_dir():
                argv = ["git", "clone"]
                if ref:
                    argv += ["--branch", ref]
                argv += [url, str(src_dir)]
                consent.announce("clone llama.cpp fork", f"{url} -> {src_dir}")
                self._run_streaming(argv, on_event, label="git clone")
        else:
            src_dir = Path(source)
            consent.announce("use local llama.cpp checkout", str(src_dir))

        cmake_flags: list[str] = []
        if instance.backend != "cpu":
            spec = _BACKEND_BUILD.get(instance.backend)
            if spec is None:
                raise RuntimeError(f"unknown backend {instance.backend!r}")
            cmake_flags.append(f"-D{spec['cmake']}=on")
        consent.announce(
            "configure llama.cpp build", "cmake -B build " + " ".join(cmake_flags)
        )
        self._run_streaming(
            ["cmake", "-B", "build", *cmake_flags],
            on_event,
            env=env,
            label="cmake configure",
            cwd=src_dir,
        )
        consent.announce("compile llama.cpp", "cmake --build build -j")
        self._run_streaming(
            ["cmake", "--build", "build", "-j"],
            on_event,
            env=env,
            label="cmake build",
            cwd=src_dir,
        )
        consent.log_action("build_llamacpp", f"{name}: {source}")

    def use(self, name: str) -> None:
        """Select ``name`` as the current engine (must be installed)."""
        self._instance(name)
        if not self.is_installed(name):
            raise RuntimeError(
                f"engine '{name}' is not installed; run `outo-llms engine install {name}`"
            )
        cfg = config_mod.load_config()
        cfg.engine.name = name
        config_mod.save_config(cfg)
        consent.log_action("use_engine", name)

    def _backend_toolchain_env(self, backend: str) -> dict[str, str]:
        """Check the backend toolchain and return a PATH-augmented env."""
        spec = _BACKEND_BUILD.get(backend)
        if spec is None:
            raise RuntimeError(
                f"unknown backend {backend!r} (choose from {', '.join(BACKEND_NAMES)})"
            )
        tool = spec["tool"]
        tool_dir: str | None = None
        if shutil.which(tool) is None:
            for candidate in _KNOWN_TOOL_DIRS.get(tool, []):
                if (Path(candidate) / tool).is_file():
                    tool_dir = candidate
                    break
            if tool_dir is None:
                raise BackendDepsError(backend, tool)
        env = os.environ.copy()
        if tool_dir is not None:
            env["PATH"] = f"{tool_dir}:{env.get('PATH', '')}"
        return env

    def _backend_env(
        self, name: str, adapter: EngineAdapter, backend: str
    ) -> dict[str, str]:
        """Build env for a pip source build with GPU support."""
        env = self._backend_toolchain_env(backend)
        consent.announce(
            f"build {adapter.display_name} with {backend.upper()} support",
            "compiles from source - this can take several minutes",
        )
        spec = _BACKEND_BUILD.get(backend)
        assert spec is not None
        env["CMAKE_ARGS"] = f"-D{spec['cmake']}=on"
        env["FORCE_CMAKE"] = "1"
        return env

    # -- run / stop ------------------------------------------------------

    def ensure_running(self, model: ModelRef, *, startup_timeout: float = 900.0) -> str:
        """Guarantee the current engine serves ``model``; return the base URL.

        Restarts the engine when a different model (or a stale process) is
        recorded. Raises RuntimeError/ValueError on setup mismatches and
        RuntimeError when the engine fails to become ready.
        """
        name = self._engine_for(model)
        instance = self._instance(name)
        adapter = self._adapter_for(name)
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
        extra_args = list(cfg.engine.extra_args)
        if not any(arg.startswith("--n_gpu_layers") for arg in extra_args):
            extra_args.extend(adapter.gpu_args(instance.backend))
        argv = adapter.serve_argv(
            self.venv_python(name), model, port, extra_args, engine_dir=self._engine_dir(name)
        )
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
                    f"engine '{name}' exited during startup (code {returncode}):\n"
                    f"{_log_error_context(log_path)}"
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

    def upgrade(self, name: str, *, on_event: Callable[[str], None] | None = None) -> None:
        """Upgrade the engine's runtime in place (new model architectures)."""
        instance = self._instance(name)
        adapter = self._adapter_for(name)
        if not self.is_installed(name):
            raise RuntimeError(
                f"engine '{name}' is not installed; run `outo-llms engine install {name}`"
            )
        running = self._live_pid(name)
        if running is not None:
            consent.announce(
                f"stop running engine '{name}' before upgrade", f"pid {running}"
            )
            self.stop()
        if isinstance(adapter, LlamaCppAdapter) and adapter.binary:
            src_dir = self._engine_dir(name) / "src"
            if not (src_dir / ".git").is_dir():
                raise RuntimeError(
                    f"engine '{name}' was built from a local checkout; "
                    "rebuild with `outo-llms engine install` after updating it yourself"
                )
            consent.announce("update llama.cpp fork", f"git -C {src_dir} pull")
            self._run_streaming(
                ["git", "-C", str(src_dir), "pull"], on_event, label="git pull"
            )
            consent.announce("recompile llama.cpp", "cmake --build build -j")
            env: dict[str, str] | None = None
            if instance.backend != "cpu":
                env = self._backend_toolchain_env(instance.backend)
            self._run_streaming(
                ["cmake", "--build", "build", "-j"],
                on_event,
                env=env,
                label="cmake build",
                cwd=src_dir,
            )
            consent.log_action("upgrade_engine", f"{name} (source rebuild)")
            return
        python = self.venv_python(name)
        consent.announce(
            f"upgrade {adapter.display_name} packages",
            ", ".join(adapter.pip_requirements),
        )
        self._run_pip(
            [str(python), "-m", "pip", "install", "--upgrade", *adapter.pip_requirements],
            on_event,
        )
        consent.log_action("upgrade_engine", name)

    def reset(self) -> None:
        """Force-stop every engine and clear all runtime state files.

        The model registry and downloaded weights are untouched; the next
        request starts a completely fresh engine process.
        """
        cfg = config_mod.load_config()
        names = list(dict.fromkeys([*self.available(), *cfg.engine.engines.keys()]))
        for name in names:
            pid = self._live_pid(name)
            if pid is not None:
                consent.announce(f"stop engine '{name}'", f"pid {pid}")
                process.kill_pid(pid)
            process.remove_pid(self._pid_path(name))
            self._port_path(name).unlink(missing_ok=True)
            self._model_path(name).unlink(missing_ok=True)
        consent.log_action("reset_engine", "all engines stopped, state cleared")

    def stop(self, name: str | None = None) -> None:
        """Stop an engine (if running) and clear its state files."""
        name = self.current_name() if name is None else name
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
        force: bool = False,
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
        name = self._engine_for(model)
        adapter = self._adapter_for(name)
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
        if force:
            consent.announce(
                f"re-download '{model.name}' with {adapter.display_name} "
                f"(cache bypassed)",
                target,
            )
        else:
            consent.announce(f"download '{model.name}' with {adapter.display_name}", target)
        argv = [str(python), "-c", _DOWNLOAD_SNIPPET, repo]
        if filename is not None:
            argv.extend(members)
        self._run_hf_snippet(
            argv,
            on_event,
            label="model download",
            extra_env={"OUTO_FORCE_DOWNLOAD": "1"} if force else None,
        )
        consent.log_action(
            "download_model", f"{name}:{model.source}{' force' if force else ''}"
        )
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
        extra_env: dict[str, str] | None = None,
    ) -> list[str]:
        """Run a huggingface_hub snippet, healing a missing module once.

        Engine venvs created before huggingface-hub became a requirement
        lack it; in that case install it into the venv and retry once.
        """
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        try:
            return self._run_streaming(argv, on_event, env=env, label=label)
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
        return self._run_streaming(argv, on_event, env=env, label=label)

    @staticmethod
    def _run_streaming(
        argv: list[str],
        on_event: Callable[[str], None] | None,
        *,
        env: dict[str, str] | None = None,
        label: str,
        cwd: Path | None = None,
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
            cwd=cwd,
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
