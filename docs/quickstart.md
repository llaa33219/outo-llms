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

This command runs setup without prompts, while still announcing and logging each action. It installs llama.cpp into its own engine virtual environment, binds the API server on `0.0.0.0:443`, generates a self-signed certificate for the auto-detected server IP, and opens the firewall on the supported Linux toolchain.

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

## 3. Create an account

Signup is open and creates a user, a `default` workspace, and the first API key. The key is returned in plaintext only in this response, so copy it immediately. Use `-k` because the certificate is self-signed:

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

Set the returned value in your shell. Replace the placeholder with the complete key, including the `outo_sk_` prefix:

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

Use the API key as a Bearer token. The proxy resolves `tinyllama` in the registry, starts the active engine on an internal loopback port if necessary, forwards the request, and returns the upstream OpenAI-style response. Keep `-k` for the self-signed certificate:

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

## 7. Inspect the deployment

The dashboard is served at the base URL. Open it in a browser:

```text
https://<your-server-ip-or-domain>/
```

The first visit shows a self-signed-certificate confirmation in the browser; accept it to load the page. The dashboard shows the server status, active engine, loaded model, workspace count, and registered model count. The Swagger UI is available at:

```text
https://<your-server-ip-or-domain>/docs
```

For more operations, see the [CLI reference](cli.md), [Server API](server-api.md), and [Configuration](configuration.md).
