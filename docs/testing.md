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
  * Expected: prints `outo-llms 0.2.2` (or the version you installed).

## Run setup

* `outo-llms setup --engine llamacpp --yes`.
  * Expected: the command announces each step. The interactive prompts default to `llamacpp`, HTTPS enabled, firewall enabled, and the auto-detected server IP for the certificate domain. Because the port is `443` (below `1024`), setup may prompt for `sudo` to run `setcap cap_net_bind_service=+ep <python>` when not running as root. It creates a venv under the data directory, installs `llama-cpp-python[server]` there, writes `config.json` with `host: 0.0.0.0`, `port: 443`, `https: true`, and the resolved `domain`, generates a self-signed certificate, opens the firewall port (Linux only), initializes `outo-llms.db`, and starts the server. The final panel shows the base URL (no `:443` suffix), the API docs URL, and the action log path.
* `outo-llms status`.
  * Expected: a `Server` table reports `running: yes`, a non-zero `pid`, `host: 0.0.0.0`, `port: 443`, `https: yes`, a `domain` row with the configured value, and a base URL like `https://203.0.113.10`. An `Engine` table reports `engine: llamacpp`, `installed: yes`, `running: no`, `port: 8612`, and `base_url: http://127.0.0.1:8612/v1`. A `Paths` table lists the config file, data dir, action log, and server log paths.

## Sign up

* `curl -ks -X POST "$BASE_URL/v1/account/signup" -H 'Content-Type: application/json' -d '{"username":"me"}'`.
  * Expected: HTTP `200` with a JSON body that includes `user_id`, `username: "me"`, `workspace: "default"`, and `api_key` starting with `outo_sk_`.
  * Save the value: `API_KEY="outo_sk_<paste-the-key>"`.
* `curl -ks "$BASE_URL/v1/account/me" -H "Authorization: Bearer $API_KEY"`.
  * Expected: HTTP `200` with the same `user_id` and `username`, and a `workspaces` array containing one entry for `default`.
* `curl -ks "$BASE_URL/v1/account/me"`.
  * Expected: HTTP `401`. The body uses the OpenAI-style error shape.

## Register and use a model

* `outo-llms models add tinyllama --source 'TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF:Q4_K_M' --kind gguf`.
  * Expected: prints `model 'tinyllama' registered` and notes that weights are downloaded on the first request.
* `outo-llms models list`.
  * Expected: a table with one row showing `tinyllama`, `gguf`, the source, and a timestamp.
* `curl -ks -X POST "$BASE_URL/v1/chat/completions" -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' -d '{"model":"tinyllama","messages":[{"role":"user","content":"Say hello in one sentence."}]}'`.
  * Expected: HTTP `200`. The body has `choices[0].message.content` with text from the model. The first request can take several minutes while llama.cpp starts and the GGUF weights download.
* `curl -ks "$BASE_URL/v1/models" -H "Authorization: Bearer $API_KEY"`.
  * Expected: HTTP `200` with `object: "list"` and a `data` array containing one entry for `tinyllama`.

## Inspect usage

* `curl -ks "$BASE_URL/v1/usage" -H "Authorization: Bearer $API_KEY"`.
  * Expected: HTTP `200`. The `workspace` field is `default`. `total_requests` is at least `1`. `by_model` contains an entry for `tinyllama` with non-zero `prompt_tokens` and `completion_tokens`.
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

## Optional: loopback HTTPS

* `outo-llms stop`, then `outo-llms setup --engine llamacpp --host 127.0.0.1 --port 8611 --https --no-open-port --yes`.
  * Expected: the wizard regenerates the configuration with `host: 127.0.0.1`, `port: 8611`, `https: true`. A self-signed certificate and key are created in the data directory's `certs/` folder.
* `outo-llms start` if setup did not start the server.
* `curl -ks https://127.0.0.1:8611/healthz`.
  * Expected: HTTP `200` with `{"status":"ok"}`.

## Optional: Dashboard and Swagger

* Open `https://<your-server-ip-or-domain>/` (the base URL printed by `outo-llms setup`, with `203.0.113.10` substituted for the placeholder) in a browser.
  * Expected: a self-signed-certificate confirmation step appears. Accept it to load an HTML page that shows `status: ok`, the active engine and its running state, the loaded model, the workspace count, and the model count. It links to `/docs` and `/healthz`.
* Open `https://<your-server-ip-or-domain>/docs` in a browser.
  * Expected: Swagger UI with the `account`, `workspaces`, `keys`, `usage`, and `proxy` route groups.

## Reset

* `outo-llms reset`.
  * Expected: the command asks two confirmation questions. Answer `y` to both.
  * The server and current engine are stopped. The complete data directory and config directory are deleted. A final message reports `outo-llms has been reset to factory state`.
* `outo-llms status`.
  * Expected: a clean status. There is no running server, no active engine entry, and the paths table still prints the default locations because they are recomputed each run.

If any step does not match its expectation, do not start the deployment for real. Inspect the action log, the server log, and the engine log, then consult the relevant docs section. Reset before retrying so the run is reproducible.