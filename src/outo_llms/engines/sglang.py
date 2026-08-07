"""SGLang engine adapter.

Serves Hugging Face models through SGLang's OpenAI-compatible server
(``python -m sglang.launch_server``). The adapter only describes what to
install and how to launch; installation happens in the engine's isolated
venv, managed by :class:`outo_llms.engines.manager.EngineManager`.

SGLang targets Linux + NVIDIA GPUs (sm80+ recommended, FlashInfer is the
default attention kernel; CUDA_HOME must be set for source builds of the
kernel packages). Its server exposes ``/v1/chat/completions``,
``/v1/completions`` and ``/v1/models`` with the same usage fields and
``stream_options.include_usage`` semantics as vLLM, so the proxy and the
manager's ``/v1/models`` readiness probe work unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from .base import EngineAdapter, ModelRef


class SglangAdapter(EngineAdapter):
    """Adapter for SGLang's ``sglang.launch_server`` module."""

    name: ClassVar[str] = "sglang"
    display_name: ClassVar[str] = "SGLang"
    pip_requirements: ClassVar[list[str]] = ["sglang"]
    default_port: ClassVar[int] = 8614

    def supports(self, model: ModelRef) -> bool:
        """SGLang serves Hugging Face models only."""
        return model.kind == "hf"

    def serve_argv(
        self,
        python: Path,
        model: ModelRef,
        port: int,
        extra_args: list[str],
        *,
        engine_dir: Path | None = None,
    ) -> list[str]:
        """Argv for SGLang's server bound to 127.0.0.1 (internal only)."""
        return [
            str(python),
            "-m",
            "sglang.launch_server",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--model-path",
            model.source,
            *extra_args,
        ]
