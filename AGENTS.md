# AGENTS.md

## Read this first

This repository is a development environment. Agents and developers **must not run automated tests, start the server, or run `outo-llms setup` here**. Make the change, verify it statically through syntax, imports, types, and code inspection, then ask the user to verify the behavior manually using [`docs/testing.md`](docs/testing.md). Do not create a local deployment as part of development work.

## Project overview

outo-llms is a Python package and PyPI-published CLI for putting local LLMs behind a managed, OpenAI-compatible API server. It installs vLLM or llama.cpp into separate engine virtual environments, then adds signup, API keys, workspaces, model registration, and per-workspace usage metering around the engine server.

The project is intentionally small and explicit. The CLI controls configuration and lifecycle, the FastAPI server owns the API surface, and a local SQLite database stores accounts, model registrations, and usage records.

## Governing philosophies

These five philosophies guide architecture and implementation decisions:

1. **Fragmentation:** Keep modules small and focused. One concern belongs in one module.
2. **Fluidity:** Features should be easy to add, replace, or remove without rewriting unrelated code.
3. **Simplicity:** A small CLI and a small API should cover the common deployment workflow.
4. **Automation:** A guided command should perform the deployment work that can be safely automated.
5. **Explicitness:** System actions are announced, confirmed when needed, and logged. The user must know what the tool is about to do.

## Repository map

- `pyproject.toml`: package metadata, Python requirement, runtime dependencies, build configuration, and the `outo-llms` console script.
- `src/outo_llms/core/`: shared paths, configuration, consent and action logging, process control, and optional HTTPS certificate handling.
- `src/outo_llms/engines/`: the engine adapter contract and lifecycle manager for isolated vLLM and llama.cpp environments.
- `src/outo_llms/server/`: FastAPI application assembly, SQLite persistence, accounts, model registry, usage metering, and the OpenAI-compatible proxy.
- `src/outo_llms/server/routes/`: account, workspace, API key, and usage route modules.
- `src/outo_llms/cli/`: Typer application assembly and one module per CLI command or command group.
- `docs/`: user-facing installation, configuration, API, operations, and testing documentation. Point users to `docs/` rather than duplicating that material in source comments or agent instructions.

**Fragmentation rule:** one concern per module. New CLI commands, engine adapters, and API route groups get their own files. Do not grow a catch-all command, adapter, or route module when a focused module will do.

## Build and development setup

The package supports Python 3.10 and newer. Create an editable development environment with:

```bash
python -m venv .venv && pip install -e .
```

The editable install exposes the `outo-llms` console script. Runtime dependencies are listed in `pyproject.toml`. Do not add a dependency, or change a dependency floor, without discussing the reason first.

Do not use this environment to perform a real setup. In particular, never run `outo-llms setup`, start `python -m outo_llms.server`, or run automated tests as part of agent work. Static checks and manual source inspection are the expected development verification. The user owns manual verification using [`docs/testing.md`](docs/testing.md).

## Explicitness and system safety

This is a critical rule. Any code path that touches the system must go through `outo_llms.core.consent`, including paths that:

- invoke subprocesses or external commands,
- change a firewall,
- write to the filesystem outside the project,
- start, stop, restart, or otherwise control processes,
- create or remove deployment state.

Use the appropriate `consent.announce`, `consent.confirm`, `consent.log_action`, and `consent.run_system` functions. Never add a silent side effect. Every automated action must leave an auditable record in `logs/actions.log`. Destructive operations need explicit confirmation. Preserve the exact command and its reason when using `run_system`.

Engines are internal services. Engine adapters must bind to `127.0.0.1`; clients access them only through the outo-llms API server. Keep API keys private. Keys use the `outo_sk_` prefix, and only the SHA-256 digest is stored. Plaintext keys are shown once at creation and must never be stored or written to logs.

## Contracts that must not break

Keep these interfaces stable unless the task explicitly changes their contract and updates every caller:

- The public `EngineManager` API in `src/outo_llms/engines/manager.py`, used by both the server and the CLI.
- The model registry functions `add_model`, `get_model`, `list_models`, and `remove_model` in `src/outo_llms/server/registry.py`.
- `db.init_db` in `src/outo_llms/server/db.py`, used by the CLI and server startup.
- The process helpers `start_server`, `stop_server`, and `restart_server` in `src/outo_llms/core/process.py`, used by the CLI.
- The console entry point `outo_llms.cli.app:main`, exposed as `outo-llms`.
- The module entry point `python -m outo_llms.server`.
- OpenAI-style error response bodies from the API. Keep SQL parameterized, and preserve workspace-scoped authentication and usage accounting.

## Code style

- Add strict type annotations to new and changed code. Do not leak `Any` into public interfaces.
- Do not add type-suppression comments. Fix the type boundary instead.
- Use `from __future__ import annotations` in Python modules.
- Prefer the standard library first. Keep third-party use aligned with the dependencies already declared in `pyproject.toml`.
- Use Pydantic v2 conventions for HTTP request and response schemas.
- Return OpenAI-style error bodies from API failures.
- Use parameterized SQL for every value passed to SQLite.
- Hash API keys with SHA-256. Never store or log plaintext keys.
- Keep modules small, focused, and easy to replace.

## Common extension tasks

### Add a CLI command

1. Create a focused module in `src/outo_llms/cli/commands/`.
2. Define the Typer command there, keeping system-touching work behind `core.consent` and existing lifecycle helpers.
3. Import and register the command in `src/outo_llms/cli/app.py`.
4. Keep user-facing instructions in `docs/` and update them when the command changes.

For a command group, use its own Typer app in its own module, as `models.py` and `engine.py` do.

### Add an engine

1. Create an adapter module in `src/outo_llms/engines/`.
2. Implement the `EngineAdapter` contract, including the supported model kind, isolated-venv requirements, default internal port, and `127.0.0.1` launch arguments.
3. Register the adapter in `engines/base.py` through `get_adapter` and `adapter_names`.
4. Keep virtualenv creation, package installation, process state, readiness checks, and logging in `EngineManager` and the consent layer. Do not install packages into the project environment.

### Add an API endpoint

1. Put a focused route group in a new module under `src/outo_llms/server/routes/` when it belongs to account, workspace, key, or usage functionality.
2. Add the router to `src/outo_llms/server/app.py`.
3. Use the shared workspace dependency for authenticated routes, and use the shared OpenAI-style error helper for API errors.
4. Preserve workspace ownership checks, parameterized SQL, and usage accounting boundaries.
5. Add or update the corresponding user-facing documentation in `docs/`.

The OpenAI-compatible proxy lives in `src/outo_llms/server/proxy.py`. Keep proxy behavior separate from account and management routes.

## Runtime locations and logs

Use `outo_llms.core.paths` instead of constructing deployment paths manually. Locations follow the platform's XDG-style directories through `platformdirs`:

- Configuration: the platform user config directory, with `outo-llms/config.json`.
- Data: the platform user data directory, with the SQLite database, model data, engine virtualenvs, certificates, PID state, and logs.
- Logs: `server.log`, `engine-<name>.log`, and `actions.log` under the outo-llms logs directory.
- Engine state: per-engine PID, port, model, and installation marker files under the engines directory.

The exact platform paths and configuration options belong in [`docs/configuration.md`](docs/configuration.md). Do not hard-code a home directory or assume that every platform uses the same XDG location.

## Verification and handoff

After editing, inspect the changed files and use static checks appropriate to the change. Confirm imports, annotations, route registration, command registration, and documented names against the implementation. Do not run tests, start the server, or run setup in this development environment. Report what was checked and ask the user to perform the manual workflow in [`docs/testing.md`](docs/testing.md).
