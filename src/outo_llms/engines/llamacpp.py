"""llama.cpp engine adapter.

Two installation modes behind one engine type:

- **pip mode** (``source=pypi``): the ``llama-cpp-python`` package, served
  with ``python -m llama_cpp.server``.
- **binary mode** (``source`` is a git URL or a local checkout): a fork of
  llama.cpp built with cmake, served with ``build/bin/llama-server``.

Both serve GGUF models through an OpenAI-compatible HTTP API on 127.0.0.1.
Installation lives in :class:`outo_llms.engines.manager.EngineManager`.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from .base import EngineAdapter, ModelRef


class LlamaCppAdapter(EngineAdapter):
    """Adapter for llama.cpp in pip mode or source-build (binary) mode."""

    name: ClassVar[str] = "llamacpp"
    display_name: ClassVar[str] = "llama.cpp (llama-cpp-python)"
    default_port: ClassVar[int] = 8612

    def __init__(self, *, binary: bool = False) -> None:
        self.binary = binary
        self.pip_requirements = (
            ["huggingface-hub>=0.24"]
            if binary
            else ["llama-cpp-python[server]>=0.2.90", "huggingface-hub>=0.24"]
        )

    def supports(self, model: ModelRef) -> bool:
        """llama.cpp serves GGUF models only."""
        return model.kind == "gguf"

    def gpu_args(self, backend: str) -> list[str]:
        """GPU offload flags for this mode; empty on the cpu backend."""
        if backend == "cpu":
            return []
        return ["-ngl", "99"] if self.binary else ["--n_gpu_layers", "-1"]

    def serve_argv(
        self,
        python: Path,
        model: ModelRef,
        port: int,
        extra_args: list[str],
        *,
        engine_dir: Path | None = None,
    ) -> list[str]:
        """Argv for the server, bound to 127.0.0.1 (internal only)."""
        if not self.binary:
            return [
                str(python),
                "-m",
                "llama_cpp.server",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                *self._model_args(model),
                *extra_args,
            ]
        if engine_dir is None:
            raise ValueError("binary mode needs the engine directory")
        server = engine_dir / "src" / "build" / "bin" / "llama-server"
        return [
            str(server),
            "--model",
            model.source,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            *extra_args,
        ]

    @staticmethod
    def _model_args(model: ModelRef) -> list[str]:
        """Map the model source to llama-cpp-python's model flags."""
        source = model.source
        if Path(source).exists():
            return ["--model", source]
        if ":" in source:
            repo, filename = source.split(":", 1)
            return ["--hf_model_repo_id", repo, "--hf_model_file", filename]
        return ["--hf_model_repo_id", source]
