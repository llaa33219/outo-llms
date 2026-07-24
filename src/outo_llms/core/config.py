"""JSON-backed configuration. Machine-managed, human-readable, stdlib only."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from . import paths


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8611
    https: bool = False
    domain: str = ""


@dataclass
class EngineInstance:
    """One engine installation: adapter type + package source + GPU backend."""

    type: str
    source: str = "pypi"
    backend: str = "vulkan"


@dataclass
class EngineConfig:
    name: str = "llamacpp"
    backend: str = "vulkan"
    extra_args: list[str] = field(default_factory=list)
    engines: dict[str, EngineInstance] = field(default_factory=dict)


_BUILTIN_INSTANCES: dict[str, EngineInstance] = {
    "llamacpp": EngineInstance(type="llamacpp", source="pypi"),
    "vllm": EngineInstance(type="vllm", source="pypi"),
}


def resolve_instance(cfg: "Config", name: str) -> EngineInstance:
    """Instance for ``name``: custom registry first, built-ins implicit."""
    custom = cfg.engine.engines.get(name)
    if custom is not None:
        return custom
    builtin = _BUILTIN_INSTANCES.get(name)
    if builtin is not None:
        return EngineInstance(
            type=builtin.type, source=builtin.source, backend=cfg.engine.backend
        )
    raise ValueError(f"unknown engine instance: {name!r}")


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)


def config_exists() -> bool:
    return paths.config_file().is_file()


def load_config() -> Config:
    """Load the config; a missing file or missing keys fall back to defaults."""
    file = paths.config_file()
    if not file.is_file():
        return Config()
    raw = json.loads(file.read_text(encoding="utf-8"))
    server_raw = raw.get("server", {})
    engine_raw = raw.get("engine", {})
    server = ServerConfig(
        host=str(server_raw.get("host", ServerConfig.host)),
        port=int(server_raw.get("port", ServerConfig.port)),
        https=bool(server_raw.get("https", ServerConfig.https)),
        domain=str(server_raw.get("domain", ServerConfig.domain)),
    )
    engine = EngineConfig(
        name=str(engine_raw.get("name", EngineConfig.name)),
        backend=str(engine_raw.get("backend", EngineConfig.backend)),
        extra_args=[str(arg) for arg in engine_raw.get("extra_args", [])],
        engines={
            str(instance_name): EngineInstance(
                type=str(instance_raw.get("type", "llamacpp")),
                source=str(instance_raw.get("source", "pypi")),
                backend=str(instance_raw.get("backend", EngineConfig.backend)),
            )
            for instance_name, instance_raw in engine_raw.get("engines", {}).items()
        },
    )
    return Config(server=server, engine=engine)


def save_config(cfg: Config) -> None:
    paths.ensure_dirs()
    paths.config_file().write_text(
        json.dumps(asdict(cfg), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
