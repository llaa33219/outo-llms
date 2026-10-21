# Server API

The API is served by FastAPI. By default setup deploys HTTPS on port `443`, so the base URL is `https://<your-server-ip-or-domain>`; the certificate is signed by the outo-llms local CA. On machines where that CA is installed (setup offers to install it on the server itself), no special handling is needed; elsewhere curl examples pass `-k` and browsers ask for a one-time confirmation. Interactive Swagger UI is at `/docs`.

Set common shell variables for the examples:

```bash
BASE_URL="https://<your-server-ip-or-domain>"
SESSION_TOKEN="outo_st_<token-from-login-or-signup>"
API_KEY="outo_sk_<key-returned-at-signup>"
```

## Authentication

> **Breaking change in 0.3.0.** outo-llms now uses two distinct credentials:
> a **session token** for account management and a **workspace API key** for
> inference. Older versions accepted only an `outo_sk_` API key for every
> authenticated route.

Two Bearer credential types are in play after signup or login:

| Credential | Prefix | Purpose | Lifetime |
| --- | --- | --- | --- |
| Session token | `outo_st_` | Account and workspace management: `me`, `login`, `logout`, `password`, `workspaces`, `workspaces/{name}/keys`, `keys/{id}`, `usage`, `status`. Also accepted by `GET /v1/models`. | 14 days. Stored as a SHA-256 hash; the plaintext is shown only at creation. |
| API key | `outo_sk_` | Inference on behalf of one workspace: `POST /v1/messages`, `POST /v1/messages/count_tokens`, plus the OpenAI compatibility endpoints `POST /v1/chat/completions` and `POST /v1/completions`. Also accepted by `GET /v1/models`. | Revoked explicitly; never auto-expires. Stored as a SHA-256 hash. |

Both are sent in the standard `Authorization: Bearer <value>` header. A missing, malformed, invalid, or revoked credential returns HTTP `401`.

Which endpoint takes which credential:

| Endpoint | Session `outo_st_` | API key `outo_sk_` |
| --- | --- | --- |
| `GET /v1/status` | yes | no |
| `POST /v1/account/signup`, `POST /v1/account/login` | open (no auth) | open (no auth) |
| `POST /v1/account/logout` | yes | no |
| `POST /v1/account/password` | yes | no |
| `GET /v1/account/me` | yes | no |
| `POST /v1/workspaces`, `GET /v1/workspaces`, `PATCH /v1/workspaces/{name}` | yes | no |
| `POST/GET /v1/workspaces/{name}/keys`, `PATCH /v1/workspaces/{name}/keys/{key_id}`, `DELETE /v1/keys/{id}` | yes | no |
| `GET /v1/usage` | yes | no |
| `GET /v1/models`, `GET /v1/models/{name}` | yes | yes (dual auth) |
| `POST /v1/messages` | no | yes |
| `POST /v1/messages/count_tokens` | no | yes |
| `POST /v1/chat/completions` | no | yes |
| `POST /v1/completions` | no | yes |

Account signup also returns both credentials in the response body, so a fresh client can use the `outo_sk_` key for inference and the `outo_st_` token for management in the same shell.

Every error response produced by outo-llms itself, including `404`, uses this error shape (the historical OpenAI-style envelope):

```json
{
  "error": {
    "message": "invalid or revoked credential",
    "type": "invalid_request_error"
  }
}
```

Some errors include a `code`, such as `model_not_found`. Request validation errors produced by FastAPI use its standard validation response.

## Status

### `GET /v1/status`

Returns the authenticated server configuration, active engine state, and aggregate user, workspace, and model counts. It requires a session token Bearer. A missing, malformed, invalid, or revoked token returns HTTP `401`.

```bash
curl -s "$BASE_URL/v1/status" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Response JSON, HTTP `200`:

```json
{
  "version": "0.3.0",
  "server": {
    "host": "0.0.0.0",
    "port": 443,
    "https": true,
    "domain": "203.0.113.10"
  },
  "engine": {
    "engine": "llamacpp",
    "installed": true,
    "running": true,
    "pid": 1842,
    "model": "tinyllama",
    "port": 8612,
    "base_url": "http://127.0.0.1:8612/v1"
  },
  "counts": {
    "users": 1,
    "workspaces": 1,
    "models": 1
  }
}
```

The `pid`, `model`, `port`, and `base_url` fields are `null` when the engine has no corresponding runtime value.

### `GET /v1/live`

Returns real-time activity: the currently loaded engine model, in-flight inference requests, and server-wide per-model call totals. Requires a session token Bearer. The web GUI's Live tab polls this endpoint.

```bash
curl -s "$BASE_URL/v1/live" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Response JSON, HTTP `200`:

```json
{
  "engine": {
    "engine": "llamacpp",
    "running": true,
    "model": "deepseek-v4-flash",
    "port": 8612,
    "loaded_at": "2026-07-23T05:00:00.123456+00:00",
    "uptime_seconds": 3600
  },
  "inflight": {
    "count": 1,
    "requests": [
      {
        "user": "luke",
        "workspace": "default",
        "model": "deepseek-v4-flash",
        "endpoint": "messages",
        "elapsed_seconds": 8.2
      }
    ]
  },
  "models": [
    {"model": "deepseek-v4-flash", "requests": 12, "total_tokens": 45678}
  ]
}
```

`model`, `port`, `loaded_at`, and `uptime_seconds` are `null` when no engine is running. `inflight.requests` lists requests currently being proxied (a streaming request stays listed until its stream finishes). `models` aggregates every workspace, ordered by request count.

## Account

> **Breaking change in 0.3.0.** Signup and login now take a password. The
> response returns both an `outo_sk_` API key (shown once, for inference) and
> an `outo_st_` session token (14 days, for management). Legacy accounts
> created before 0.3.0 have no password and cannot log in; their existing API
> keys keep working for inference, and a fresh signup or `outo-llms reset`
> produces a working account.

### `POST /v1/account/signup`

Creates a user, the user's `default` workspace, the first API key, and the first session token. This endpoint is open and does not require an Authorization header.

Request JSON:

```json
{
  "username": "me",
  "password": "correct horse battery staple"
}
```

`username` is required and must be between 1 and 64 characters. `password` is required and must be at least 8 characters.

```bash
curl -s -X POST "$BASE_URL/v1/account/signup" \
  -H 'Content-Type: application/json' \
  -d '{"username":"me","password":"correct horse battery staple"}'
```

Response JSON, HTTP `200`:

```json
{
  "user_id": 1,
  "username": "me",
  "workspace": "default",
  "api_key": "outo_sk_<random-value>",
  "session_token": "outo_st_<random-value>"
}
```

The plaintext `api_key` and `session_token` are returned only at creation time. Save them both: the API key is used for inference, the session token for account management. A duplicate username returns HTTP `409`.

### `POST /v1/account/login`

Exchanges a username and password for a fresh session token.

Request JSON:

```json
{
  "username": "me",
  "password": "correct horse battery staple"
}
```

```bash
curl -s -X POST "$BASE_URL/v1/account/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"me","password":"correct horse battery staple"}'
```

Response JSON, HTTP `200`:

```json
{
  "session_token": "outo_st_<random-value>",
  "user_id": 1,
  "username": "me",
  "workspaces": [
    {
      "id": 1,
      "name": "default",
      "created_at": "2026-07-18T12:00:00+00:00"
    }
  ]
}
```

Wrong credentials return a generic HTTP `401` with the same body shape as other errors, so the endpoint cannot be used for username enumeration. The plaintext session token is returned only at creation time.

### `POST /v1/account/logout`

Revokes the calling session token. Requires a session Bearer. Revocation makes the token fail authentication on every subsequent call.

```bash
curl -s -X POST "$BASE_URL/v1/account/logout" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Response JSON, HTTP `200`:

```json
{
  "revoked": true
}
```

### `POST /v1/account/password`

Changes the calling user's password and revokes every active session token for that user. The user is signed out of every device and must log in again. API keys are not affected.

Request JSON:

```json
{
  "current_password": "correct horse battery staple",
  "new_password": "new pass phrase here"
}
```

`new_password` must be at least 8 characters.

```bash
curl -s -X POST "$BASE_URL/v1/account/password" \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"current_password":"correct horse battery staple","new_password":"new pass phrase here"}'
```

Response JSON, HTTP `200`:

```json
{
  "changed": true
}
```

A wrong `current_password` returns HTTP `401`.

### `GET /v1/account/me`

Returns the authenticated user's identity and all workspaces owned by that user. Requires a session Bearer.

```bash
curl -s "$BASE_URL/v1/account/me" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Response JSON, HTTP `200`:

```json
{
  "user_id": 1,
  "username": "me",
  "workspaces": [
    {
      "id": 1,
      "name": "default",
      "created_at": "2026-07-18T12:00:00+00:00"
    }
  ]
}
```

## Workspaces

### `POST /v1/workspaces`

Creates a workspace owned by the authenticated user.

Request JSON:

```json
{
  "name": "experiments"
}
```

`name` is required and must be between 1 and 64 characters.

```bash
curl -s -X POST "$BASE_URL/v1/workspaces" \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"experiments"}'
```

Response JSON, HTTP `200`:

```json
{
  "id": 2,
  "name": "experiments",
  "created_at": "2026-07-18T12:05:00+00:00",
  "limits": {
    "total": null,
    "monthly": null,
    "weekly": null,
    "five_hour": null
  }
}
```

The `limits` field is the workspace's own token budget; a new workspace starts with every period unset. See [Token limits](#token-limits). A duplicate workspace name for the same user returns HTTP `409`.

### `GET /v1/workspaces`

Lists every workspace owned by the authenticated user. Each entry includes the workspace's own `limits`.

```bash
curl -s "$BASE_URL/v1/workspaces" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Response JSON, HTTP `200`:

```json
[
  {
    "id": 1,
    "name": "default",
    "created_at": "2026-07-18T12:00:00+00:00",
    "limits": {
      "total": null,
      "monthly": null,
      "weekly": null,
      "five_hour": null
    }
  },
  {
    "id": 2,
    "name": "experiments",
    "created_at": "2026-07-18T12:05:00+00:00",
    "limits": {
      "total": null,
      "monthly": null,
      "weekly": null,
      "five_hour": null
    }
  }
]
```

## API keys

> **API keys are inference-only credentials in 0.3.0.** They authenticate
> `POST /v1/messages` (and its OpenAI compatibility siblings) plus `GET /v1/models`
> on behalf of one workspace. They do not authenticate workspace management,
> usage, account, or status endpoints; those require a session token.

### `POST /v1/workspaces/{name}/keys`

Creates a key for a workspace owned by the authenticated user. The path `name` is the workspace name, not its numeric id.

Request JSON:

```json
{
  "label": "local development",
  "limits": {
    "total": 100000,
    "monthly": 50000,
    "weekly": null,
    "five_hour": null
  }
}
```

`label` is optional and defaults to an empty string. `limits` is optional; omit it to create a key with no limits. When present, each entry sets a token budget for one period. An integer (>= 1) sets the limit; an explicit `null` clears that period's limit (treated as unset). Omitted entries stay unset. An unset period is unlimited. See [Token limits](#token-limits) for the full rule set and enforcement behavior.

```bash
curl -s -X POST "$BASE_URL/v1/workspaces/experiments/keys" \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"label":"local development","limits":{"total":100000,"monthly":50000}}'
```

Response JSON, HTTP `200`:

```json
{
  "id": 3,
  "api_key": "outo_sk_<random-value>",
  "label": "local development",
  "workspace": "experiments",
  "limits": {
    "total": 100000,
    "monthly": 50000,
    "weekly": null,
    "five_hour": null
  }
}
```

The plaintext key is returned once. The `limits` field echoes the value that was persisted (omitted fields appear as `null`). A key for a workspace the authenticated user does not own returns HTTP `404`.

### `GET /v1/workspaces/{name}/keys`

Lists key metadata for an owned workspace. It never returns plaintext keys or stored hashes.

```bash
curl -s "$BASE_URL/v1/workspaces/experiments/keys" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Response JSON, HTTP `200`:

```json
[
  {
    "id": 1,
    "label": "local development",
    "created_at": "2026-07-18T12:06:00+00:00",
    "revoked": false,
    "limits": {
      "total": 100000,
      "monthly": 50000,
      "weekly": null,
      "five_hour": null
    }
  }
]
```

The `limits` field is the key's own token budget. A period with a `null` value is unset (unlimited). See [Token limits](#token-limits).

### `DELETE /v1/keys/{key_id}`

Revokes a key belonging to any workspace owned by the authenticated user. Revocation makes the key fail authentication. The key remains as metadata with `revoked: true`.

```bash
curl -s -X DELETE "$BASE_URL/v1/keys/1" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Response JSON, HTTP `200`:

```json
{
  "revoked": true
}
```

A key that is not owned by the user, or does not exist, returns HTTP `404`.

### `PATCH /v1/workspaces/{name}/keys/{key_id}`

Updates an existing key's `label` and/or `limits`. Body fields are independent; omitted fields stay unchanged. Owned-key semantics are the same as `DELETE /v1/keys/{key_id}`.

Request JSON:

```json
{
  "label": "renamed",
  "limits": {
    "total": 200000,
    "monthly": null
  }
}
```

`label` is optional. `limits` is optional and applies the same rule as `POST /v1/workspaces/{name}/keys`: an integer (>= 1) sets that period, an explicit `null` clears that period, omitted entries stay unchanged. Omit `limits` entirely to leave every period as it was.

```bash
curl -s -X PATCH "$BASE_URL/v1/workspaces/experiments/keys/3" \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"limits":{"total":200000,"monthly":null}}'
```

Response JSON, HTTP `200`:

```json
{
  "id": 3,
  "label": "local development",
  "created_at": "2026-07-18T12:06:00+00:00",
  "revoked": false,
  "limits": {
    "total": 200000,
    "monthly": null,
    "weekly": null,
    "five_hour": null
  }
}
```

A key that is not owned by the user, or does not exist, returns HTTP `404`. Setting a limit value below `1` returns HTTP `400`.

## Token limits

Both an API key and its workspace can carry their own token budgets. Each budget covers four periods:

| Period | Scope |
| --- | --- |
| `total` | All recorded usage since the key was created. |
| `monthly` | The current UTC calendar month. |
| `weekly` | The current ISO week, UTC. |
| `five_hour` | The rolling 5-hour window ending at request time. |

For every period, an integer (>= 1) sets the budget and an explicit `null` clears it. A period that is unset is unlimited. Before forwarding a chat or legacy completion, the server computes the period totals for the calling key and for its workspace and rejects the request if either would exceed any set budget. Both checks apply; whichever trips first blocks the request.

Enforcement looks at already-recorded usage, so a single in-flight request may push a counter slightly past a budget; usage is recorded after the response. This matches the best-effort accounting already used for streaming responses.

### `PATCH /v1/workspaces/{name}`

Updates the workspace's `limits`. Body fields are independent; omitted fields stay unchanged.

Request JSON:

```json
{
  "limits": {
    "monthly": 1000000,
    "five_hour": 50000
  }
}
```

`limits` is optional. When present, the same rule applies: an integer sets that period, an explicit `null` clears it, omitted entries stay unchanged. Omit `limits` entirely to leave every period as it was.

```bash
curl -s -X PATCH "$BASE_URL/v1/workspaces/experiments" \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"limits":{"monthly":1000000,"five_hour":50000}}'
```

Response JSON, HTTP `200`:

```json
{
  "id": 2,
  "name": "experiments",
  "created_at": "2026-07-18T12:05:00+00:00",
  "limits": {
    "total": null,
    "monthly": 1000000,
    "weekly": null,
    "five_hour": 50000
  }
}
```

A workspace the authenticated user does not own returns HTTP `404`. Setting a limit value below `1` returns HTTP `400`. The `limits` field is also returned on `GET /v1/workspaces`.

### Rate-limit error response

When a request would exceed a set budget, the inference endpoints (`POST /v1/messages`, `POST /v1/chat/completions`, `POST /v1/completions`) return HTTP `429` with the standard error body:

```json
{
  "error": {
    "message": "token limit reached",
    "type": "invalid_request_error",
    "code": "rate_limit_exceeded"
  }
}
```

The check runs before the request is forwarded to the engine, so a rejected request never reaches the upstream. The same shape is used for key limits and workspace limits; the message identifies the budget that was hit.

## Usage

### `GET /v1/usage`

Returns aggregate usage for the caller. Requires a session Bearer. Usage is grouped by model.

An optional `?workspace=<name>` query parameter selects one of the caller's workspaces. The named workspace must belong to the authenticated user; asking about someone else's workspace returns HTTP `404`. Without the parameter, the response aggregates across every workspace owned by the caller and the `workspace` field in the response is the string `all`.

Aggregate across every workspace owned by the caller:

```bash
curl -s "$BASE_URL/v1/usage" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Scope to one workspace:

```bash
curl -s "$BASE_URL/v1/usage?workspace=experiments" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Response JSON, HTTP `200` (aggregate form):

```json
{
  "workspace": "all",
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

The `workspace` field echoes the chosen scope, either `all` or the single workspace name.

For non-streaming proxy responses, accounting reads the upstream response's usage fields - `usage.input_tokens`/`usage.output_tokens` on the Anthropic surface, `usage.prompt_tokens`/`usage.completion_tokens` on the OpenAI surface - and records them as prompt and completion tokens. Missing values are treated as zero. For streaming responses, the proxy forwards the SSE stream unchanged and reads usage from the stream's usage events (`message_start` + final `message_delta` for Anthropic; the final usage-bearing event for OpenAI, requested via `stream_options.include_usage: true`). Streaming accounting is best effort and never breaks the stream.

## Models

### `GET /v1/models`

Lists registered models in the OpenAI `list` shape (kept for broad client compatibility; every inference SDK can discover models from it). This is the registry exposed by outo-llms, not a direct listing from the engine. Accepts either a session Bearer or an API key Bearer, so both GUI and inference clients can call it with the credential they already hold.

```bash
curl -s "$BASE_URL/v1/models" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Or with an API key:

```bash
curl -s "$BASE_URL/v1/models" \
  -H "Authorization: Bearer $API_KEY"
```

Response JSON, HTTP `200`:

```json
{
  "object": "list",
  "data": [
    {
      "id": "tinyllama",
      "object": "model",
      "created": 0,
      "owned_by": "outo-llms"
    }
  ]
}
```

### `GET /v1/models/{name}`

Returns the registry detail for one model. Accepts either a session Bearer or an API key Bearer, like the list endpoint. The web UI's model page uses it together with generated curl/Python/Node.js request examples.

```bash
curl -s "$BASE_URL/v1/models/tinyllama" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Response JSON, HTTP `200`:

```json
{
  "name": "tinyllama",
  "source": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
  "kind": "hf",
  "created_at": "2026-07-19T07:10:14.026930+00:00"
}
```

The `{name}` path segment accepts slashes, so registry names that mirror a Hugging Face repository id (`org/model`) work without URL escaping:

```bash
curl -s "$BASE_URL/v1/models/org/model" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Unknown model names return `404` with code `model_not_found`.

## Inference proxy (Anthropic primary, OpenAI compatibility)

The primary inference surface is the Anthropic Messages API. The OpenAI endpoints are kept as a compatibility surface; both are proxied to the same engine with the same auth, limits, and usage accounting.

### `POST /v1/messages`

Forwards an Anthropic Messages request to the active engine. The JSON body must be an object with a registered `model` string and follows the [Anthropic Messages API](https://docs.anthropic.com/en/api/messages): `messages` and `max_tokens` are required upstream; `system`, `temperature`, `top_p`, `top_k`, `stop_sequences`, `tools`, and `tool_choice` are forwarded as-is.

```bash
curl -s "$BASE_URL/v1/messages" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "tinyllama",
    "max_tokens": 1024,
    "messages": [
      {"role":"user","content":"What is 2 plus 2?"}
    ],
    "temperature": 0.2
  }'
```

The response is the upstream engine response. A typical response has this shape:

```json
{
  "id": "msg_example",
  "type": "message",
  "role": "assistant",
  "content": [
    {"type": "text", "text": "2 plus 2 is 4."}
  ],
  "model": "tinyllama",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 18,
    "output_tokens": 8
  }
}
```

The exact id, text, and token counts come from the engine. A missing `model` returns HTTP `400`. An unregistered model returns HTTP `404` with code `model_not_found`. If the active engine is not installed or cannot start the selected model, the proxy returns HTTP `502`. If a token limit on the calling key or its workspace would be exceeded, the proxy returns HTTP `429` with the standard error body shown in [Token limits](#token-limits) and never forwards the request.

### `POST /v1/messages/count_tokens`

Forwards a token-counting request to the active engine (llama.cpp, vLLM, and SGLang all implement it). The body takes the same fields as `POST /v1/messages` except `max_tokens`, which is not required. The response is the upstream `{"input_tokens": ...}` payload. Usage is not recorded for token counting - nothing is generated.

```bash
curl -s "$BASE_URL/v1/messages/count_tokens" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "tinyllama",
    "messages": [
      {"role":"user","content":"What is 2 plus 2?"}
    ]
  }'
```

### OpenAI compatibility endpoints

`POST /v1/chat/completions` and `POST /v1/completions` forward OpenAI-format requests to the active engine, exactly as before; the body must contain a registered `model` string and other fields are forwarded. These exist for existing OpenAI clients - new integrations should prefer `POST /v1/messages`.

```bash
curl -s "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "tinyllama",
    "messages": [
      {"role":"user","content":"What is 2 plus 2?"}
    ]
  }'
```

The response is the upstream OpenAI-shaped response (`choices`, `usage.prompt_tokens`/`completion_tokens`). The same 400/404/429/502 errors apply.

### Streaming

Set `"stream": true` in the `POST /v1/messages` body (or in the OpenAI compatibility requests). The proxy returns `text/event-stream` and forwards the upstream Anthropic SSE events (`message_start`, `content_block_delta`, `message_delta`, `message_stop`) unchanged. Token counts are read from the `message_start` and final `message_delta` events for accounting.

```bash
curl -N "$BASE_URL/v1/messages" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "tinyllama",
    "max_tokens": 1024,
    "messages": [{"role":"user","content":"Say hello."}],
    "stream": true
  }'
```

## Health and web GUI

### `GET /healthz`

Open endpoint for a lightweight health check.

```bash
curl -s "$BASE_URL/healthz"
```

Response JSON:

```json
{
  "status": "ok"
}
```

### `GET /`

Serves the built-in web GUI on the same host and port as the API, for example `https://your-server-ip/`. It is a dependency-free single-page app written with vanilla HTML, CSS, and JavaScript. It has no CDN dependencies, so it works offline on a LAN once the server is reachable. The old inline HTML dashboard has been replaced by this GUI. Swagger UI remains available at `/docs`.

The top bar contains four views: `Models`, `Workspaces`, `Server status`, and `Profile`.

* **Profile.** The GUI stores the session token in the browser's `localStorage`. `Sign up` accepts a username and password (minimum 8 characters), creates an account, and displays the new `outo_st_` session token and `outo_sk_` API key once with copy buttons. `Log in` accepts an existing username and password, validates them with `POST /v1/account/login`, and stores the returned session token. `Log out` posts to `POST /v1/account/logout` and clears the stored token. The GUI never stores or displays the password again after signup or login.
* **Models.** Shows a read-only list of registered models. Add, download, and remove operations remain CLI-only: `outo-llms models add`, `outo-llms models download`, `outo-llms models list`, and `outo-llms models remove`.
* **Workspaces.** Lists and creates workspaces. For each workspace, the GUI lists, creates, and revokes API keys. New keys are shown once with a copy button. It also shows the usage summary for the workspace associated with the current key.
* **Server status.** Shows the version, server host, port, HTTPS setting, domain, engine installed and running state, engine model and port, and user, workspace, and model counts.

The static assets are packaged under `src/outo_llms/server/ui/static/` as `index.html`, `app.js`, and `style.css`. The server serves the entry page at `/` and named assets at `/ui/<name>`. If the assets are missing, `GET /` returns a JSON `404` response.

```bash
curl -s "$BASE_URL/"
```

Open the same URL in a browser to use the rendered GUI.

## Anthropic SDK compatibility

The proxy's primary surface is the Anthropic Messages API. Configure an Anthropic client with the outo-llms base URL and an `outo_sk_...` key. The SDK sends the key as a Bearer token (`auth_token`), which is what outo-llms expects:

```python
from anthropic import Anthropic

client = Anthropic(
    base_url="https://<your-server-ip-or-domain>",
    auth_token="outo_sk_<key-created-by-signup>",
)

response = client.messages.create(
    model="tinyllama",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Say hello."}],
)
print(response.content[0].text)
```

On machines where the outo-llms local CA is installed, no special client handling is needed. Otherwise, download the server's `certs/ca.crt` and pass it as the CA bundle (for the Anthropic Python client, an `httpx.Client` configured with `verify="/path/to/ca.crt"`), or disable verification in non-production environments (`verify=False`).

OpenAI clients keep working against the compatibility surface: point an OpenAI SDK at `https://<your-server-ip-or-domain>/v1` with an `outo_sk_...` key and call `chat.completions.create(...)` as usual.
