# Architecture

This page describes the module boundaries, the request flow, and the extension points. The implementation is deliberately small. Each concern lives in one module.

## Module map

```text
src/outo_llms/
├── __init__.py             package metadata and version
├── __main__.py             `python -m outo_llms` placeholder
├── core/
│   ├── paths.py            XDG-style paths and directory creation
│   ├── config.py           JSON-backed server and engine configuration
│   ├── consent.py          announce, confirm, confirm_twice, log_action, run_system
│   ├── process.py          server start, stop, restart, pid helpers, port polling
│   └── certs.py            local-CA and CA-signed certificate generation for HTTPS
├── engines/
│   ├── base.py             EngineAdapter contract, ModelRef, adapter registry
│   ├── llamacpp.py         llama.cpp adapter and serve argv
│   ├── vllm.py             vLLM adapter and serve argv
│   └── manager.py          EngineManager: install, use, ensure_running, stop
├── server/
│   ├── __main__.py         uvicorn entry point: `python -m outo_llms.server`
│   ├── app.py              FastAPI factory, lifespan, /healthz, /
│   ├── db.py               SQLite connection, schema, init_db, utcnow
│   ├── accounts.py         users, workspaces, key issue/revoke/verify
│   ├── registry.py         model registry CRUD
│   ├── usage.py            usage record and aggregate summary
│   ├── schemas.py          Pydantic v2 request and response models
│   ├── deps.py             OpenAI-style error helper, WorkspaceDep auth dependency
│   ├── proxy.py            OpenAI-compatible proxy with usage accounting
│   └── routes/
│       ├── account.py      POST /v1/account/signup, GET /v1/account/me
│       ├── workspaces.py   POST /v1/workspaces, GET /v1/workspaces
│       ├── keys.py         POST/GET /v1/workspaces/{name}/keys, DELETE /v1/keys/{key_id}
│       └── usage.py        GET /v1/usage
└── cli/
    ├── app.py              Typer application, command registration
    └── commands/
        ├── setup.py        outo-llms setup
        ├── start.py        outo-llms start
        ├── stop.py         outo-llms stop
        ├── restart.py      outo-llms restart
        ├── status.py       outo-llms status
        ├── reset.py        outo-llms reset
        ├── version.py      outo-llms version
        ├── models.py       outo-llms models add/list/remove
        └── engine.py       outo-llms engine list/use/install/status
```

## Layered responsibilities

The implementation is layered:

* `core/` is shared infrastructure. It has no knowledge of engine adapters, accounts, or HTTP routes.
* `engines/` knows about adapters and how to run them. It calls `core/` for paths, consent, configuration, and process control.
* `server/` knows about HTTP, persistence, accounts, the proxy, and the OpenAI-compatible surface. It calls `engines/` lazily for inference and `core/` for shared helpers.
* `cli/` knows about the user command surface. It calls into the same modules as the server.

The boundaries mean a change to a CLI command does not change the server, and a change to an engine adapter does not change accounts or the CLI.

## Request flow

```text
client                outo-llms API server                EngineManager       engine subprocess
  │                          │                                  │                    │
  │ HTTP /v1/chat/...        │                                  │                    │
  │ (Bearer outo_sk_...)     │                                  │                    │
  │ ────────────────────────▶                                  │                    │
  │                          │ require_workspace():            │                    │
  │                          │   parse header, verify key      │                    │
  │                          │   → WorkspaceContext            │                    │
  │                          │ resolve model in registry       │                    │
  │                          │ ensure_running(model_ref) ─────▶│                    │
  │                          │                                  │ start / reuse      │
  │                          │                                  │ engine process ───▶│
  │                          │                                  │ poll /v1/models    │
  │                          │                                  │ until 200          │
  │                          │ ensure_running returns base_url │                    │
  │                          │ proxy.forward → upstream URL    │                    │
  │                          │ ────────────────────────────────▶ ──────────────────▶│
  │                          │                                  │                    │ run inference
  │                          │ ◀──────────────────────────────── ───────────────────│
  │                          │ record usage (non-stream or     │                    │
  │                          │   final SSE event with usage)   │                    │
  │ ◀────────────────────────                                  │                    │
  │ OpenAI-style response or SSE stream                        │                    │
```

For `chat/completions` and `completions`, the proxy does the following:

1. Parse and validate the JSON body.
2. Resolve the `model` field against the registry. Missing `model` is HTTP `400`. Unknown model is HTTP `404` with `code: "model_not_found"`.
3. Call `EngineManager.ensure_running(model_ref)` to start or reuse the engine. A missing engine installation or an unsupported kind is HTTP `502`.
4. Forward the request to the upstream OpenAI-compatible URL on `127.0.0.1:<engine-port>`.
5. For non-streaming responses, parse JSON, read `usage.prompt_tokens` and `usage.completion_tokens`, and record a usage row.
6. For streaming responses, set `stream_options.include_usage: true`, stream SSE bytes, then inspect the assembled text for a usage-bearing event and record usage best effort.

The same dependency authenticates every authenticated route. Errors return through the OpenAI-style error helper in `server/deps.py`.

## Process model

```text
shell
└── outo-llms start    (this process exits after subprocess.Popen + PID write)
    └── python -m outo_llms.server        (API server, detached via start_new_session=True)
        ├── uvicorn loop
        │   ├── /healthz, /, /docs
        │   ├── /v1/account/signup, /v1/account/me
        │   ├── /v1/workspaces, /v1/workspaces/{name}/keys
        │   ├── /v1/keys/{key_id}
        │   ├── /v1/usage
        │   └── /v1/models, /v1/chat/completions, /v1/completions
        └── EngineManager.ensure_running on demand
            └── python -m llama_cpp.server (or vllm.entrypoints.openai.api_server)
```

The API server is a detached process with output redirected to `data/logs/server.log`. Its PID is stored in `data/server.pid`. `outo-llms stop` reads the PID file, sends SIGTERM, waits for the process to exit, and sends SIGKILL if needed.

Engine processes follow the same pattern with PID, port, and model name written directly under `data/engines/`. `EngineManager` reuses a running engine when the same model is requested, and it stops and restarts the engine when a different model is requested or when a stale PID is detected.

The `__main__.py` for `outo_llms.server` calls `uvicorn.run(...)` with the configured host and port. If HTTPS is enabled, it asks `core/certs.py` for a CA-signed pair and passes them to Uvicorn.

## How fragmentation and fluidity show up

* **Adding an engine.** Create a new module under `src/outo_llms/engines/` with a class that extends `EngineAdapter`. Add its name to `adapter_names()` and the lookup in `get_adapter()`. The manager, server, and CLI pick it up automatically.
* **Adding a CLI command.** Create a new module under `src/outo_llms/cli/commands/` with a Typer function. Register it in `src/outo_llms/cli/app.py`. For a command group, create a Typer app and use `app.add_typer`.
* **Adding an HTTP route.** Create a new module under `src/outo_llms/server/routes/` with a router. Include it in `src/outo_llms/server/app.py`. Use the `WorkspaceDep` dependency for authenticated routes and the `openai_error` helper for OpenAI-style error responses.
* **Adding configuration.** Extend a dataclass in `src/outo_llms/core/config.py`. The loader falls back to defaults for missing keys, so older `config.json` files still work.

The [development guide](development.md) walks through each extension in detail.

## Data and persistence

SQLite is the only database. The schema covers five tables: `users`, `workspaces`, `api_keys`, `models`, and `usage`. The schema is created by `db.init_db()` from a single `CREATE TABLE IF NOT EXISTS` script. All timestamps are UTC ISO-8601 strings. Foreign keys are enabled per connection. Queries use parameter binding.

The `EngineManager` keeps no in-memory state between calls. All state lives on disk: `config.json`, engine marker files, engine PID, port, model files, the database, the action log, and engine and server logs.

## What does not change

These are stable contracts documented for users and contributors:

* The `EngineManager` API in `engines/manager.py`.
* The registry functions `add_model`, `get_model`, `list_models`, and `remove_model` in `server/registry.py`.
* `db.init_db` in `server/db.py`.
* The process helpers `start_server`, `stop_server`, and `restart_server` in `core/process.py`.
* The console entry point `outo_llms.cli.app:main`, exposed as `outo-llms`.
* The module entry point `python -m outo_llms.server`.
* The OpenAI-style error shape.

Changes to those contracts require updates to every caller and to the documentation.