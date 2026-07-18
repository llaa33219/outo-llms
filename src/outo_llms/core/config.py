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


@dataclass
class EngineConfig:
    name: str = "llamacpp"
    extra_args: list[str] = field(default_factory=list)


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
    )
    engine = EngineConfig(
        name=str(engine_raw.get("name", EngineConfig.name)),
        extra_args=[str(arg) for arg in engine_raw.get("extra_args", [])],
    )
    return Config(server=server, engine=engine)


def save_config(cfg: Config) -> None:
    paths.ensure_dirs()
    paths.config_file().write_text(
        json.dumps(asdict(cfg), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
