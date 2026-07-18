"""vLLM engine adapter.

Serves Hugging Face models through vLLM's OpenAI-compatible API server.
The adapter only describes what to install and how to launch; installation
happens in the engine's isolated venv, managed by
:class:`outo_llms.engines.manager.EngineManager`.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from .base import EngineAdapter, ModelRef


class VllmAdapter(EngineAdapter):
    """Adapter for vLLM's ``vllm.entrypoints.openai.api_server`` module."""

    name: ClassVar[str] = "vllm"
    display_name: ClassVar[str] = "vLLM"
    pip_requirements: ClassVar[list[str]] = ["vllm>=0.6"]
    default_port: ClassVar[int] = 8613

    def supports(self, model: ModelRef) -> bool:
        """vLLM serves Hugging Face models only."""
        return model.kind == "hf"

    def serve_argv(
        self, python: Path, model: ModelRef, port: int, extra_args: list[str]
    ) -> list[str]:
        """Argv for vLLM's API server bound to 127.0.0.1 (internal only)."""
        return [
            str(python),
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--model",
            model.source,
            *extra_args,
        ]
