"""Single source of truth for every filesystem location outo-llms uses.

Paths follow the XDG base directory spec via ``platformdirs``:

- config: ``~/.config/outo-llms/config.json``
- data:   ``~/.local/share/outo-llms/`` (db, engines, models, certs, logs)

``reset`` simply deletes the config and data directories, which returns the
tool to a truly fresh state.
"""

from pathlib import Path

from platformdirs import PlatformDirs

_dirs = PlatformDirs(appname="outo-llms", appauthor=False)


def config_dir() -> Path:
    return Path(_dirs.user_config_dir)


def data_dir() -> Path:
    return Path(_dirs.user_data_dir)


def engines_dir() -> Path:
    return data_dir() / "engines"


def models_dir() -> Path:
    return data_dir() / "models"


def certs_dir() -> Path:
    return data_dir() / "certs"


def logs_dir() -> Path:
    return data_dir() / "logs"


def db_path() -> Path:
    return data_dir() / "outo-llms.db"


def pid_file() -> Path:
    return data_dir() / "server.pid"


def server_log() -> Path:
    return logs_dir() / "server.log"


def config_file() -> Path:
    return config_dir() / "config.json"


def action_log() -> Path:
    return logs_dir() / "actions.log"


def ensure_dirs() -> None:
    for directory in (
        config_dir(),
        data_dir(),
        engines_dir(),
        models_dir(),
        certs_dir(),
        logs_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)
