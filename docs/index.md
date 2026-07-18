# outo-llms documentation

outo-llms deploys local language models behind a managed, OpenAI-compatible API server. The server adds account signup, workspace-scoped API keys, model registration, and per-workspace usage metering around either llama.cpp or vLLM.

The inference engine runs in an isolated virtual environment managed by outo-llms. It does not install engine packages into the Python environment that contains the `outo-llms` command.

## 60-second orientation

1. Install the package with `pipx install outo-llms` or `pip install outo-llms`.
2. Run `outo-llms setup`. Choose an engine, server address, HTTPS setting, and firewall behavior. Setup creates the data directories, database, isolated engine environment, and background server.
3. Create an account with `POST /v1/account/signup`. The response contains the first API key and the `default` workspace. Save the key. Its plaintext is returned only when it is created.
4. Register a model with `outo-llms models add ...`.
5. Send an authenticated request to `POST /v1/chat/completions` or `POST /v1/completions`. The engine starts when the first request needs it.
6. Inspect metering at `GET /v1/usage`, the dashboard at `/`, or the interactive API reference at `/docs`.

The default server is `http://127.0.0.1:8611`. llama.cpp uses port `8612` by default and vLLM uses port `8613` by default. Those engine ports are internal and are not the client API.

## Documentation map

* [Philosophy](philosophy.md) explains the five design principles and where they appear in the source.
* [Installation](installation.md) covers package installation, operating systems, hardware, and model access tokens.
* [Quickstart](quickstart.md) walks through setup, signup, model registration, a first completion, and usage inspection.
* [CLI reference](cli.md) documents every `outo-llms` command and option.
* [Server API](server-api.md) documents every HTTP endpoint, authentication rule, payload, and response.
* [Engines](engines.md) compares llama.cpp and vLLM and explains isolation, model sources, and lifecycle behavior.
* [Configuration](configuration.md) describes `config.json`, the data directories, state files, and logs.
* [Security](security.md) covers API keys, workspace boundaries, network binding, HTTPS, firewall changes, and audit logging.
* [Architecture](architecture.md) describes the module boundaries, request flow, process model, and extension points.
* [Development](development.md) gives contributor setup and rules for adding commands, engines, routes, and releases.
* [Testing](testing.md) is the manual verification checklist. The development environment does not run automated tests.

## Choose the next page

* New user: start with the [installation guide](installation.md), then follow the [quickstart](quickstart.md).
* API client author: read [Server API](server-api.md).
* Operator: read [CLI reference](cli.md), [Configuration](configuration.md), and [Security](security.md).
* Contributor: read [Architecture](architecture.md), [Development](development.md), and [Testing](testing.md).
