"""SGLang engine adapter.

Serves Hugging Face models through SGLang's OpenAI-compatible server
(``python -m sglang.launch_server``). The adapter only describes what to
install and how to launch; installation happens in the engine's isolated
venv, managed by :class:`outo_llms.engines.manager.EngineManager`.

SGLang targets Linux + NVIDIA GPUs (sm80+ recommended, FlashInfer is the
default attention kernel; CUDA_HOME must be set for source builds of the
kernel packages). Its server exposes the Anthropic Messages API (``/v1/messages``, with
``usage.input_tokens``/``usage.output_tokens``) next to the OpenAI
endpoints and ``/v1/models``, so the proxy and the manager's ``/v1/models``
readiness probe work unchanged.
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
    # cuda uses the PyPI wheels; rocm is a source build. No Vulkan or CPU
    # backend exists upstream - llama.cpp covers those.
    supported_backends: ClassVar[list[str]] = ["cuda", "rocm"]
    default_backend: ClassVar[str] = "cuda"

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
