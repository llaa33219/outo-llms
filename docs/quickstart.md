# Quickstart

This guide uses the default server-first deployment, llama.cpp, and a small GGUF model from Hugging Face. It assumes Python 3.10 or newer and a working `pipx` or `pip` installation.

## 1. Install outo-llms

```bash
pipx install outo-llms
```

For a regular Python environment, use `python -m pip install outo-llms` instead. Check the command:

```bash
outo-llms version
```

## 2. Run setup

This command runs setup without prompts, while still announcing and logging each action. It installs llama.cpp into its own engine virtual environment, binds the API server on `0.0.0.0:443`, creates a local CA and signs a server certificate for the auto-detected server IP, installs the CA into the system trust store on supported Linux systems, and opens the firewall on the supported Linux toolchain.

```bash
outo-llms setup --engine llamacpp --yes
```

When the port is below `1024` and outo-llms is not running as root, setup asks once for `sudo` to grant bind permission via `setcap`. With `--yes` that step is auto-confirmed.

The default API base URL is the server's HTTPS address on port `443` (no port in the URL). Substitute your own server IP or domain for `<your-server-ip-or-domain>`; this guide uses the documentation placeholder `203.0.113.10`:

```text
https://<your-server-ip-or-domain>
# example for a machine reached at 203.0.113.10
https://203.0.113.10
```

Setup also prints the API documentation URL and the action log path. If engine installation fails, inspect the setup output and the paths shown by `outo-llms status`.

## 3. Open the web GUI and create an account

The built-in web GUI is served at the same base URL as the API. Open it in a browser:

```text
https://<your-server-ip-or-domain>/
```

In the `Profile` menu, choose `Sign up`, enter a username, and submit the form. The GUI displays the new API key once with a copy button. Copy and save the key immediately. The GUI stores the key in the browser's `localStorage`, so you can use `Profile` > `Log in` later to paste an existing key, or `Log out` to clear it.

For API users who prefer curl, signup remains available as an open endpoint:

```bash
BASE_URL="https://203.0.113.10"

curl -ks -X POST "$BASE_URL/v1/account/signup" \
  -H 'Content-Type: application/json' \
  -d '{"username":"me"}'
```

Example response shape:

```json
{
  "user_id": 1,
  "username": "me",
  "workspace": "default",
  "api_key": "outo_sk_<random-value>"
}
```

Set the returned value in your shell. If you signed up in the GUI, use the copied value instead. Replace the placeholder with the complete key, including the `outo_sk_` prefix:

```bash
API_KEY="outo_sk_<paste-the-key-from-signup>"
```

## 4. Register a GGUF model

The registry name is the name clients send in the `model` field. With llama.cpp, the source can use Hugging Face `repo:file` syntax. This example selects the `Q4_K_M` file from the TinyLlama GGUF repository.

```bash
outo-llms models add tinyllama \
  --source 'TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF:Q4_K_M' \
  --kind gguf
```

Weights are downloaded on the first request, not by `models add`. The first request can therefore take time while the engine starts and downloads the model.

Check the registry if needed:

```bash
outo-llms models list
```

For a vLLM setup, select `vllm` during setup and register a Hugging Face repository as kind `hf`:

```bash
outo-llms setup --engine vllm --yes
outo-llms models add tinyllama \
  --source 'TinyLlama/TinyLlama-1.1B-Chat-v1.0' \
  --kind hf
```

Use one setup path in a fresh installation. Switching engines later is covered in [Engines](engines.md).

## 5. Send the first chat completion

Use the API key as a Bearer token. The proxy resolves `tinyllama` in the registry, starts the active engine on an internal loopback port if necessary, forwards the request, and returns the upstream OpenAI-style response. The trust store already trusts the local CA on the server, so no `-k` is needed; on other machines that have not installed `ca.crt`, pass `-k` until they do:

```bash
curl -ks "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "tinyllama",
    "messages": [
      {"role": "user", "content": "Say hello in one sentence."}
    ]
  }'
```

The engine starts on demand. llama.cpp listens internally on port `8612` by default. The client should continue to use the managed API server at the base URL above.

## 6. Inspect usage

The proxy records the upstream response's `usage` token counts against the workspace associated with the API key.

```bash
curl -ks "$BASE_URL/v1/usage" \
  -H "Authorization: Bearer $API_KEY"
```

Example response shape after one successful request:

```json
{
  "workspace": "default",
  "total_requests": 1,
  "total_tokens": 42,
  "by_model": [
    {
      "model": "tinyllama",
      "requests": 1,
      "prompt_tokens": 18,
      "completion_tokens": 24,
      "total_tokens": 42
    }
  ]
}
```

The actual token counts come from the engine response and will vary.

## 7. Use the web GUI

The built-in web GUI is a dependency-free single-page app written with vanilla HTML, CSS, and JavaScript. It has no CDN dependencies, so it works offline on a LAN once the server is reachable. Open the base URL:

```text
https://<your-server-ip-or-domain>/
```

The top bar provides four views:

* **Models** lists registered models. This view is read-only. Register or remove models with the CLI commands `outo-llms models add`, `outo-llms models list`, and `outo-llms models remove`.
* **Workspaces** lists and creates workspaces. For each workspace, you can list, create, and revoke API keys. New keys are shown once with a copy button. The view also shows the usage summary for the workspace associated with the current key.
* **Server status** shows the version, server host, port, HTTPS setting, domain, engine state, and user, workspace, and model counts.
* **Profile** manages the current browser key. Use `Log in` to paste an existing key, `Sign up` to create an account and receive a key once, or `Log out` to clear the key from local storage.

The first visit loads with no certificate warning because the local CA is already trusted on this machine. On machines that have not installed `ca.crt`, browsers show a warning; install the CA from `data/certs/ca.crt` and the warning goes away. See [Security](security.md) for per-OS instructions. The Swagger UI is available at:

```text
https://<your-server-ip-or-domain>/docs
```

For more operations, see the [CLI reference](cli.md), [Server API](server-api.md), and [Configuration](configuration.md).
