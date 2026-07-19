"""llama.cpp engine adapter.

Serves GGUF models through ``llama_cpp.server`` (the OpenAI-compatible
server bundled with llama-cpp-python). The adapter only describes what to
install and how to launch; installation happens in the engine's isolated
venv, managed by :class:`outo_llms.engines.manager.EngineManager`.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from .base import EngineAdapter, ModelRef


class LlamaCppAdapter(EngineAdapter):
    """Adapter for llama.cpp via the ``llama-cpp-python[server]`` package."""

    name: ClassVar[str] = "llamacpp"
    display_name: ClassVar[str] = "llama.cpp (llama-cpp-python)"
    pip_requirements: ClassVar[list[str]] = [
        "llama-cpp-python[server]>=0.2.90",
        "huggingface-hub>=0.24",
    ]
    default_port: ClassVar[int] = 8612

    def supports(self, model: ModelRef) -> bool:
        """llama.cpp serves GGUF models only."""
        return model.kind == "gguf"

    def serve_argv(
        self, python: Path, model: ModelRef, port: int, extra_args: list[str]
    ) -> list[str]:
        """Argv for ``llama_cpp.server`` bound to 127.0.0.1 (internal only)."""
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

    @staticmethod
    def _model_args(model: ModelRef) -> list[str]:
        """Map the model source to llama-cpp-python's model flags.

        A local path is passed as-is; ``repo:filename`` selects a file from
        a Hugging Face repo; anything else is treated as a HF repo id.
        """
        source = model.source
        if Path(source).exists():
            return ["--model", source]
        if ":" in source:
            repo, filename = source.split(":", 1)
            return ["--hf_model_repo_id", repo, "--hf_model_file", filename]
        return ["--hf_model_repo_id", source]
