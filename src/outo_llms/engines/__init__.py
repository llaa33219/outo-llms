"""Inference engine adapters and lifecycle management (isolated venvs)."""

from .base import EngineAdapter, ModelRef, adapter_names, get_adapter
from .manager import EngineManager

__all__ = [
    "EngineAdapter",
    "EngineManager",
    "ModelRef",
    "adapter_names",
    "get_adapter",
]
