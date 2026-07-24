"""Engine adapter contract.

An *engine adapter* knows how to install and launch one inference backend
(vLLM, llama.cpp). Adapters never install anything themselves - installation
is the manager's job, inside an isolated venv. The adapter only describes
*what* to install and *how* to launch a model.

Adding a new engine = adding one adapter module and registering it in
:func:`get_adapter` / :func:`adapter_names`. Nothing else changes (fluidity).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class ModelRef:
    """A model as registered in the outo-llms registry."""

    name: str  # registry name used by clients, e.g. "tinyllama"
    source: str  # HF repo id, or a path to a local .gguf file
    kind: str  # "hf" | "gguf"
    engine: str | None = None  # engine instance pinned to this model (None = default)


class EngineAdapter(ABC):
    """Describes one inference backend."""

    name: ClassVar[str]
    display_name: ClassVar[str]
    pip_requirements: ClassVar[list[str]]
    default_port: ClassVar[int]

    @abstractmethod
    def serve_argv(
        self, python: Path, model: ModelRef, port: int, extra_args: list[str]
    ) -> list[str]:
        """Argv that starts an OpenAI-compatible server for ``model``.

        ``python`` is the engine venv's interpreter. The server must bind
        127.0.0.1 (engines are never exposed directly)."""

    @abstractmethod
    def supports(self, model: ModelRef) -> bool:
        """Whether this engine can serve the given model."""


def adapter_names() -> list[str]:
    return ["llamacpp", "vllm"]


def get_adapter(name: str) -> EngineAdapter:
    if name == "llamacpp":
        from .llamacpp import LlamaCppAdapter

        return LlamaCppAdapter()
    if name == "vllm":
        from .vllm import VllmAdapter

        return VllmAdapter()
    raise ValueError(
        f"unknown engine: {name!r} (available: {', '.join(adapter_names())})"
    )
