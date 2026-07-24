# outo-llms documentation

outo-llms deploys local language models behind a managed, OpenAI-compatible API server. The server adds password-protected accounts with session tokens, workspace-scoped API keys for inference, model registration with immediate weight download, and per-workspace usage metering around either llama.cpp or vLLM.

The inference engine runs in an isolated virtual environment managed by outo-llms. It does not install engine packages into the Python environment that contains the `outo-llms` command.

## 60-second orientation

1. Install the package with `uv tool install outo-llms` (or `pipx`/`pip`).
2. Run `outo-llms setup`. Choose an engine, server address, HTTPS setting, and firewall behavior. Setup creates the data directories, database, isolated engine environment, and background server.
3. Open the web GUI at `/` and use `Profile` > `Sign up` to create an account with a username and password. Save the `outo_st_` session token and `outo_sk_` API key when they are displayed once. API users can create an account with `POST /v1/account/signup {"username","password"}` instead.
4. Register a model with `outo-llms models add ...`. The command downloads the weights into the shared Hugging Face cache immediately, so the first inference request does not have to.
5. Send an authenticated request to `POST /v1/chat/completions` or `POST /v1/completions` with the API key. The engine starts when the first request needs it; the weights are already cached.
6. Inspect metering at `GET /v1/usage` with the session token (use `?workspace=<name>` to scope to one workspace), use the full web GUI at `/` for signup and login, read-only model browsing, workspace and API-key management, and server status, or open the interactive API reference at `/docs`.

By default the server listens on `0.0.0.0:443` with HTTPS, so the web GUI is at `https://<your-server-ip-or-domain>/` with no port in the URL. llama.cpp uses port `8612` by default and vLLM uses port `8613` by default. Those engine ports are internal and are not the client API.

## Documentation map

* [Philosophy](philosophy.md) explains the five design principles and where they appear in the source.
* [Installation](installation.md) covers package installation, operating systems, hardware, and model access tokens.
* [Quickstart](quickstart.md) walks through setup, signup, model registration, a first completion, and usage inspection.
* [CLI reference](cli.md) documents every `outo-llms` command and option.
* [Server API](server-api.md) documents every HTTP endpoint, authentication rule, payload, and response.
* [Engines](engines.md) compares llama.cpp and vLLM and explains isolation, model sources, downloads, and lifecycle behavior.
* [Configuration](configuration.md) describes `config.json`, the data directories, state files, and logs.
* [Security](security.md) covers the credential model (passwords, sessions, API keys), workspace boundaries, network binding, HTTPS, firewall changes, and audit logging.
* [Architecture](architecture.md) describes the module boundaries, request flow, process model, and extension points.
* [Development](development.md) gives contributor setup and rules for adding commands, engines, routes, and releases.
* [Testing](testing.md) is the manual verification checklist. The development environment does not run automated tests.

## Choose the next page

* New user: start with the [installation guide](installation.md), then follow the [quickstart](quickstart.md).
* API client author: read [Server API](server-api.md).
* Operator: read [CLI reference](cli.md), [Configuration](configuration.md), and [Security](security.md).
* Contributor: read [Architecture](architecture.md), [Development](development.md), and [Testing](testing.md).
