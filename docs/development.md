# Development

This page describes how to set up a development environment, the project's coding rules, how to add new features, and how to build a release.

## Repository layout

```text
outo-llms/
├── pyproject.toml         hatchling build, dependencies, console script entry point
├── README.md              short introduction with link to docs/
├── .github/workflows/     release automation (PyPI trusted publishing)
├── src/
│   └── outo_llms/         all package source
└── docs/                  user documentation
```

The package uses a `src/` layout. Hatchling builds the wheel from `src/outo_llms` and the source distribution also includes `docs/`, `README.md`, and `LICENSE`.

## Dev environment

The package supports Python 3.10 and newer. A typical setup:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the package in editable mode and registers the `outo-llms` console script. Verify the install:

```bash
outo-llms version
```

Do not run `outo-llms setup`, start the server, or run automated tests in this environment. The development environment is for editing, static checks, and inspection. Manual verification belongs to the user and is described in [Testing](testing.md).

## Code style

* Every new or changed module imports `from __future__ import annotations`.
* Use the standard library first. Keep third-party imports aligned with the dependencies in `pyproject.toml`.
* Public interfaces should have strict types. Do not leak `Any`. Fix the type boundary rather than suppress it.
* HTTP request and response shapes use Pydantic v2 `BaseModel`s in `server/schemas.py`.
* Every SQL value is passed as a parameter. Concatenation of values into SQL is not allowed.
* API keys are stored as SHA-256 hex digests. Plaintext keys are never logged.
* Modules are small and focused. Add a new module when a concern does not fit an existing one. Avoid growing catch-all modules.
* Every system-touching code path must go through `core/consent.py`. That includes subprocess invocation, filesystem writes outside the project tree, process control, firewall changes, and certificate generation. The hard rule is the same for contributors: outo-llms never touches the system without announcing it.
* Web UI container changes (layout, window types, gaps, borders, window animations) follow [`style.md`](../style.md) (BLP TILE). Inner component visuals follow the dark console tokens in `src/outo_llms/server/ui/static/style.css`.

## Adding a CLI command

1. Create a new module under `src/outo_llms/cli/commands/` with a Typer function.
2. If the command groups several subcommands, define a Typer app in the module the way `commands/models.py` and `commands/engine.py` do.
3. Register the command or group in `src/outo_llms/cli/app.py` with `app.command(...)` or `app.add_typer(...)`.
4. Touch the system only through `core.consent`. Announce, optionally confirm, and `log_action`.
5. Update the [CLI reference](cli.md) and any other affected docs.

Example skeleton for a single command:

```python
# src/outo_llms/cli/commands/health.py
from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def health() -> None:
    """Print a one-line health summary."""
    from ...core import process

    running = process.is_server_running()
    console.print("ok" if running else "stopped")
```

Register it in `cli/app.py`:

```python
from .commands import health

app.command("health")(health.health)
```

## Adding an engine adapter

1. Create `src/outo_llms/engines/<name>.py` with a class that extends `EngineAdapter`.
2. Declare the class vars `name`, `display_name`, `pip_requirements`, and `default_port`.
3. Implement `supports(model: ModelRef) -> bool`. The kind check is the simplest rule, but more elaborate adapters are allowed.
4. Implement `serve_argv(python, model, port, extra_args) -> list[str]`. The argv must bind `127.0.0.1` because engines are never exposed directly.
5. Register the adapter in `engines/base.py` by adding its name to `adapter_names()` and a branch in `get_adapter()`.
6. Update the [Engines](engines.md) page and any other affected docs.

Minimum adapter:

```python
# src/outo_llms/engines/example.py
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from .base import EngineAdapter, ModelRef


class ExampleAdapter(EngineAdapter):
    name: ClassVar[str] = "example"
    display_name: ClassVar[str] = "Example engine"
    pip_requirements: ClassVar[list[str]] = ["example-package>=0"]
    default_port: ClassVar[int] = 8614

    def supports(self, model: ModelRef) -> bool:
        return model.kind == "hf"

    def serve_argv(
        self, python: Path, model: ModelRef, port: int, extra_args: list[str]
    ) -> list[str]:
        return [
            str(python),
            "-m",
            "example.server",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--model", model.source,
            *extra_args,
        ]
```

## Adding an HTTP route

1. Create `src/outo_llms/server/routes/<group>.py` with an `APIRouter` and route functions.
2. Add Pydantic request and response models in `src/outo_llms/server/schemas.py` for any new request and response bodies.
3. For authenticated routes, take the dependency that matches the credential: `ctx: UserDep` for account management (session token) or `ctx: WorkspaceDep` for inference (API key). Use `SessionOrWorkspaceDep` only when both are valid, as with `GET /v1/models`.
4. Use the `openai_error` helper from `src/outo_llms/server/deps.py` to produce OpenAI-style error responses.
5. Include the router in `src/outo_llms/server/app.py` with `app.include_router(...)`.
6. Update the [Server API](server-api.md) page.

## Adding a configuration field

1. Extend the dataclass in `src/outo_llms/core/config.py`. The loader already tolerates missing keys, so older `config.json` files continue to load.
2. If the new field needs setup input, add the option to the Typer command in `cli/commands/setup.py` and write the new value in the saved configuration.
3. Document the field in [Configuration](configuration.md).

## Releases

Releases are published to PyPI by GitHub Actions using **trusted publishing** (OIDC). No PyPI API token is stored anywhere; PyPI authenticates the repository directly. The workflow lives at `.github/workflows/release.yml` and runs when a `v*` tag is pushed: it builds the sdist and wheel with Hatchling, then publishes them with `pypa/gh-action-pypi-publish` under an `id-token: write` permission.

One-time PyPI setup (maintainer): register a *pending publisher* at <https://pypi.org/manage/account/publishing/> with owner `llaa33219`, repository `outo-llms`, workflow name `release.yml`, and no environment. The first release then creates the PyPI project automatically.

Cutting a release:

```bash
# 1. Bump the version in src/outo_llms/__init__.py and pyproject.toml (they must agree).
# 2. Commit and push.
# 3. Tag the release and push the tag - the workflow does the rest.
git tag v<version>
git push origin v<version>
```

The wheel contains `src/outo_llms`. The sdist additionally bundles `docs/`, `README.md`, and `LICENSE`. To build distributions locally (e.g. to inspect them):

```bash
python -m pip install build
python -m build
```

Before a release:

* Update the version string in `src/outo_llms/__init__.py` and `pyproject.toml`. They must agree.
* Update the README quickstart and the docs that reference defaults, ports, paths, or features.
* Confirm that the package still imports, the console script entry point resolves, and the API surface listed in [Server API](server-api.md) and the [CLI reference](cli.md) matches the code.

## When you change something

* Keep the listed stable contracts intact unless the change is part of a deliberate contract change that updates every caller and the docs. The stable contracts are listed in [Architecture](architecture.md).
* Keep API key plaintext out of logs and the action log.
* Keep the OpenAI-style error response shape.
* Keep the engine adapters bound to `127.0.0.1`.