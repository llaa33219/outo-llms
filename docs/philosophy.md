# Philosophy

outo-llms is organized around five principles. They describe both the user experience and the shape of the implementation.

## Fragmentation

Split the system by function so each part is easy to extend, change, remove, or manage. Core filesystem, configuration, consent, process control, and certificate work live separately from engine adapters, server features, and CLI commands.

The module map is:

* `core/` owns paths, JSON configuration, explicit action handling, process control, and certificates.
* `engines/` owns the adapter contract, the llama.cpp adapter, the vLLM adapter, and the lifecycle manager.
* `server/` owns the SQLite database, accounts, workspaces, keys, model registry, usage ledger, routes, and OpenAI-compatible proxy.
* `cli/` owns the `outo-llms` command tree and one module per command area.

See the complete [architecture map](architecture.md). The boundaries mean an API route does not need to know how an engine virtual environment is created, and a model command does not need to know how a request is proxied.

## Fluidity

Features should be possible to add or remove as needs change without rewriting unrelated parts. Engine support is the clearest example. An engine implements the `EngineAdapter` contract in `engines/base.py`, gets a registry entry in `get_adapter()` and `adapter_names()`, and the manager can install and run it. The rest of the server and CLI use the manager interface.

The same pattern applies to CLI work. A new command belongs in a module under `cli/commands/` and is registered in `cli/app.py`. A new route belongs in a route module and is included by the application factory.

## Simplicity

A small command set and a small GUI cover the normal lifecycle. `setup` creates a working deployment. `models add`, `models list`, and `models remove` manage the registry. The engine, server, and reset commands cover the remaining operational actions. The web GUI at `/` offers signup and login, a read-only model catalog, workspace and API-key management, and server status. Swagger UI at `/docs` exposes the HTTP API interactively.

The implementation keeps configuration human-readable in one JSON file and persistence local in one SQLite database. Clients can use ordinary `curl` requests or an OpenAI-compatible SDK.

## Automation

A working deployment should come from a few explicit commands, not a long manual installation recipe. `outo-llms setup` creates the XDG directories, writes configuration, initializes SQLite, creates an isolated virtual environment for the selected engine, installs the engine requirements there, optionally creates a local CA and a CA-signed certificate, optionally invokes a Linux firewall tool, and starts the server in the background.

The engine manager automates the next part. When a request names a registered model, it starts the active engine if needed, waits for its internal `/v1/models` endpoint to respond, and forwards the request through the managed API server.

## Explicitness

Automation is never silent. `core/consent.py` is the implementation of this principle:

* `announce()` tells the user what is about to happen.
* `confirm()` gates actions that need a yes or no decision.
* `confirm_twice()` protects the destructive `reset` command.
* `run_system()` announces, optionally confirms, logs, and then runs an external command without a shell.
* `log_action()` writes an auditable record.

The action log is `logs/actions.log` under the data directory. Setup, server lifecycle actions, engine lifecycle actions, certificate generation, firewall commands, and reset are logged. The `--yes` setup option removes prompts, but it does not remove announcements or logging. The hard rule is that outo-llms never touches the system without announcing the action and recording it where the implementation supports logging.

Read [Security](security.md) for the operational consequences and [Configuration](configuration.md) for the exact locations.
