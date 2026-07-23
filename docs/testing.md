# Testing

outo-llms does not run automated tests inside its development environment. The repository is structured so that changes are validated by code review and static inspection. The user is responsible for running a complete, real deployment to confirm behavior.

This page is a manual verification checklist. Run it end-to-end after a fresh installation or after a change that affects setup, the proxy, the engine lifecycle, accounts, or configuration.

Each item lists one command or request and what to look for in the result.

## Prepare

Pick an environment you are willing to reset. The checklist ends with a reset that deletes the complete outo-llms data and config directories. Use a clean user account or a test machine.

Set shell variables that the rest of the checklist uses. The base URL is the server's HTTPS address on port `443` (no port suffix). Substitute the address printed by `outo-llms setup`; this example uses the documentation placeholder `203.0.113.10`:

```bash
BASE_URL="https://203.0.113.10"
```

## Install

* `pip install outo-llms` (or `pipx install outo-llms`).
  * Expected: the command exits with status `0`. No traceback. The package is installed.
* `outo-llms version`.
  * Expected: prints `outo-llms 0.6.2` (or the version you installed).

## Run setup

* `outo-llms setup --engine llamacpp --yes`.
  * Expected: the command announces each step. The interactive prompts default to `llamacpp`, HTTPS enabled, trust-store installation enabled, firewall enabled, and the auto-detected server IP for the certificate domain. Because the port is `443` (below `1024`), setup may prompt for `sudo` to run `setcap cap_net_bind_service=+ep <python>` when not running as root. It creates a venv under the data directory, installs `llama-cpp-python[server]` there, writes `config.json` with `host: 0.0.0.0`, `port: 443`, `https: true`, and the resolved `domain`, creates the local CA in `certs/ca.crt` and `certs/ca.key` (key mode `0600`), signs the server certificate at `certs/server.crt` and `certs/server.key`, installs `ca.crt` into the system trust store (Linux only, via sudo), opens the firewall port (Linux only), initializes `outo-llms.db`, and starts the server. The final panel shows the base URL (no `:443` suffix), the API docs URL, and the action log path.
* `outo-llms status`.
  * Expected: a `Server` table reports `running: yes`, a non-zero `pid`, `host: 0.0.0.0`, `port: 443`, `https: yes`, a `domain` row with the configured value, and a base URL like `https://203.0.113.10`. An `Engine` table reports `engine: llamacpp`, `installed: yes`, `running: no`, `port: 8612`, and `base_url: http://127.0.0.1:8612/v1`. A `Paths` table lists the config file, data dir, action log, and server log paths.

## Sign up

* `curl -ks -X POST "$BASE_URL/v1/account/signup" -H 'Content-Type: application/json' -d '{"username":"me","password":"correct horse battery staple"}'`.
  * Expected: HTTP `200` with a JSON body that includes `user_id`, `username: "me"`, `workspace: "default"`, an `api_key` starting with `outo_sk_`, and a `session_token` starting with `outo_st_`. Save both values: `API_KEY="outo_sk_<paste-the-key>"` and `SESSION_TOKEN="outo_st_<paste-the-token>"`.
* `curl -ks "$BASE_URL/v1/account/me" -H "Authorization: Bearer $SESSION_TOKEN"`.
  * Expected: HTTP `200` with the same `user_id` and `username`, and a `workspaces` array containing one entry for `default`.
* `curl -ks "$BASE_URL/v1/account/me" -H "Authorization: Bearer $API_KEY"`.
  * Expected: HTTP `401`. Management endpoints require a session token, not an API key. The body uses the OpenAI-style error shape.
* `curl -ks "$BASE_URL/v1/account/me"`.
  * Expected: HTTP `401`. The body uses the OpenAI-style error shape.

## Log in and rotate credentials

* `curl -ks -X POST "$BASE_URL/v1/account/login" -H 'Content-Type: application/json' -d '{"username":"me","password":"correct horse battery staple"}'`.
  * Expected: HTTP `200` with a fresh `session_token` (different from the signup one), the `user_id`, the `username`, and the `workspaces` array. Save it: `SESSION_TOKEN="outo_st_<paste-the-new-token>"`.
* `curl -ks -X POST "$BASE_URL/v1/account/login" -H 'Content-Type: application/json' -d '{"username":"me","password":"wrong password"}'`.
  * Expected: HTTP `401`. The body is the generic OpenAI-style error, not a different message for wrong-username vs wrong-password.
* `curl -ks -X POST "$BASE_URL/v1/account/logout" -H "Authorization: Bearer $SESSION_TOKEN"`.
  * Expected: HTTP `200` with `{"revoked": true}`.
* `curl -ks "$BASE_URL/v1/account/me" -H "Authorization: Bearer $SESSION_TOKEN"`.
  * Expected: HTTP `401`. The revoked session no longer authenticates. Re-login to continue.
* `curl -ks -X POST "$BASE_URL/v1/account/password" -H "Authorization: Bearer $SESSION_TOKEN" -H 'Content-Type: application/json' -d '{"current_password":"correct horse battery staple","new_password":"another pass phrase"}'`.
  * Expected: HTTP `200` with `{"changed": true}`. Every active session for the user is now revoked; logging in again with the new password succeeds.

## Register and use a model

* `outo-llms models add tinyllama --source 'TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF:Q4_K_M' --kind gguf`.
  * Expected: streams download progress from `huggingface_hub` as the file is fetched into the shared cache (`~/.cache/huggingface`), then prints `model 'tinyllama' registered`. The first inference request no longer has to download weights.
* `outo-llms models add tinyllama --source 'TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF' --kind gguf` (no `:file`, no `--no-download`, with several `.gguf` files in the repo).
  * Expected: an interactive numbered picker listing each `.gguf`. Pick one by number to download that file, or run with a non-interactive stdin to see the file list and the `--source repo:file` hint instead.
* `outo-llms models add tinyllama --source 'TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF:Q4_K_M' --kind gguf --no-download`.
  * Expected: registration succeeds without downloading. `outo-llms models download tinyllama` later fetches the file into the same cache; rerunning `download` is idempotent.
* `outo-llms models list`.
  * Expected: a table with one row showing `tinyllama`, `gguf`, the source, and a timestamp.
* `curl -ks -X POST "$BASE_URL/v1/chat/completions" -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' -d '{"model":"tinyllama","messages":[{"role":"user","content":"Say hello in one sentence."}]}'`.
  * Expected: HTTP `200`. The body has `choices[0].message.content` with text from the model. Because the weights were pre-downloaded at registration, the first request only waits for llama.cpp to start the engine.
* `curl -ks "$BASE_URL/v1/models" -H "Authorization: Bearer $API_KEY"`.
  * Expected: HTTP `200` with `object: "list"` and a `data` array containing one entry for `tinyllama`.
* `curl -ks "$BASE_URL/v1/models" -H "Authorization: Bearer $SESSION_TOKEN"`.
  * Expected: same `200` response. `GET /v1/models` accepts either a session token or an API key.

## Inspect usage

* `curl -ks "$BASE_URL/v1/usage" -H "Authorization: Bearer $SESSION_TOKEN"`.
  * Expected: HTTP `200`. The `workspace` field is the string `all`. `total_requests` is at least `1`. `by_model` contains an entry for `tinyllama` with non-zero `prompt_tokens` and `completion_tokens`.
* `curl -ks "$BASE_URL/v1/usage?workspace=default" -H "Authorization: Bearer $SESSION_TOKEN"`.
  * Expected: HTTP `200`. The `workspace` field is `default`. Counts match the request that ran on that workspace.
* `curl -ks "$BASE_URL/v1/usage?workspace=does-not-exist" -H "Authorization: Bearer $SESSION_TOKEN"`.
  * Expected: HTTP `404` with the OpenAI-style error shape. The named workspace either does not exist or is not owned by the caller.
* Send another completion with a different prompt and re-issue the usage request.
  * Expected: `total_requests` increments and token totals increase.

## Engine and server lifecycle

* `outo-llms engine status`.
  * Expected: `engine: llamacpp`, `installed: yes`, `running: yes`, a non-zero `pid`, `model: tinyllama`, `port: 8612`, `base_url: http://127.0.0.1:8612/v1`, `server running: yes`, and a `server pid`.
* `outo-llms restart`.
  * Expected: prints `server restarted`. `outo-llms status` still shows the server as `running` with a fresh PID.
* `outo-llms stop`.
  * Expected: prints `server stopped`. `outo-llms status` shows `running: no` and `pid: -`.
* `outo-llms start`.
  * Expected: prints `server started`. `outo-llms status` shows `running: yes` again.

## Engine switching (optional, recommended)

* `outo-llms engine install vllm`.
  * Expected: a venv under `data/engines/vllm/venv/` is created, `vllm` is pip-installed there, and an `INSTALLED` marker is written.
* `outo-llms engine use vllm`.
  * Expected: prints `active engine: vllm`.
* `outo-llms models add hf-tinyllama --source 'TinyLlama/TinyLlama-1.1B-Chat-v1.0' --kind hf`.
  * Expected: the model is registered.
* Issue a completion against `hf-tinyllama` with the same API key.
  * Expected: the vLLM engine starts on its internal port (default `8613`), the request is forwarded, and `GET /v1/usage` now shows a row for `hf-tinyllama`.
  * Note: switching engines does not retroactively affect previously registered models. `outo-llms models download hf-tinyllama` re-fetches with the new engine's HF cache if needed.

## Optional: loopback HTTPS

* `outo-llms stop`, then `outo-llms setup --engine llamacpp --host 127.0.0.1 --port 8611 --https --no-trust-store --no-open-port --yes`.
  * Expected: the wizard regenerates the configuration with `host: 127.0.0.1`, `port: 8611`, `https: true`. The local CA is reused and the server certificate is regenerated in the data directory's `certs/` folder (`ca.crt`, `ca.key`, `server.crt`, `server.key`).
* `outo-llms start` if setup did not start the server.
* `curl -ks https://127.0.0.1:8611/healthz`.
  * Expected: HTTP `200` with `{"status":"ok"}`. With `--no-trust-store`, `-k` is still required on this machine. After rerunning setup without `--no-trust-store` (or by manually installing `certs/ca.crt`), plain `curl https://127.0.0.1:8611/healthz` works without `-k`.

## Web GUI

* Open `https://<your-server-ip-or-domain>/` in a browser.
  * Expected: the dependency-free single-page GUI loads at the base URL. On a machine that has not installed `ca.crt`, the browser shows a certificate warning until the CA is trusted.
* Open `Profile`, choose `Sign up`, enter a new username and a password (at least 8 characters), and submit.
  * Expected: the account is created, the new session token and API key are displayed once with copy buttons, and the session token is saved in the browser. Copy and save both values before leaving the screen. The password is never displayed or stored after signup.
* Open `Profile`, choose `Log out`.
  * Expected: the stored session token is cleared. Subsequent requests fail with `401` until you log in again.
* Open `Profile`, choose `Log in`, enter the same username and password.
  * Expected: a new session token is fetched from `POST /v1/account/login` and stored. The rest of the GUI works again.
* Open the `Models` view.
  * Expected: the registered model list is visible and read-only. There are no model add, download, or remove actions in the GUI; use `outo-llms models add`, `outo-llms models download`, `outo-llms models list`, or `outo-llms models remove` for those operations.
* Open the `Workspaces` view and create a workspace.
  * Expected: the new workspace appears in the workspace list, and the usage summary for the workspaces owned by the current session is visible.
* In the new workspace, create an API key, then revoke it.
  * Expected: the new key is displayed once with a copy button, appears in the workspace key list as active, and then appears as revoked after the revoke action. The revoked key no longer authenticates requests.
* Open the `Server status` view.
  * Expected: the page shows the version, server host, port, HTTPS setting, domain, engine installed and running state, engine model and port, and user, workspace, and model counts.

## Swagger UI

* Open `https://<your-server-ip-or-domain>/docs` in a browser.
  * Expected: Swagger UI with the `account`, `workspaces`, `keys`, `usage`, and `proxy` route groups, including `GET /v1/status`. The `Authorize` button accepts an `outo_st_` session token; `outo_sk_` API keys work only on the endpoints that accept them.

## Reset

* `outo-llms reset`.
  * Expected: the command asks two confirmation questions. Answer `y` to both.
  * The server and current engine are stopped. The complete data directory and config directory are deleted. A final message reports `outo-llms has been reset to factory state`.
* `outo-llms status`.
  * Expected: a clean status. There is no running server, no active engine entry, and the paths table still prints the default locations because they are recomputed each run.

If any step does not match its expectation, do not start the deployment for real. Inspect the action log, the server log, and the engine log, then consult the relevant docs section. Reset before retrying so the run is reproducible.