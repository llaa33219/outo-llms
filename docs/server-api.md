# Server API

The API is served by FastAPI. The default base URL is `http://127.0.0.1:8611`. If setup enables HTTPS, replace `http` with `https` and account for the self-signed certificate. Interactive Swagger UI is at `/docs`.

Set common shell variables for the examples:

```bash
BASE_URL="http://127.0.0.1:8611"
API_KEY="outo_sk_<key-created-by-signup>"
```

## Authentication

Signup is the only account endpoint that is open. All other `/v1` endpoints require:

```http
Authorization: Bearer outo_sk_...
```

The key resolves to one workspace context. Workspace, key, usage, model, and proxy requests are evaluated in that authenticated context. A missing, malformed, invalid, or revoked key returns HTTP `401`.

Application errors use an OpenAI-style error object inside FastAPI's `detail` field:

```json
{
  "detail": {
    "error": {
      "message": "invalid or revoked API key",
      "type": "invalid_request_error"
    }
  }
}
```

Some errors include a `code`, such as `model_not_found`. Request validation errors produced by FastAPI can use its standard validation response.

## Account

### `POST /v1/account/signup`

Creates a user, the user's `default` workspace, and the first API key. This endpoint is open and does not require an Authorization header.

Request JSON:

```json
{
  "username": "me"
}
```

`username` is required and must be between 1 and 64 characters.

```bash
curl -s -X POST "$BASE_URL/v1/account/signup" \
  -H 'Content-Type: application/json' \
  -d '{"username":"me"}'
```

Response JSON, HTTP `200`:

```json
{
  "user_id": 1,
  "username": "me",
  "workspace": "default",
  "api_key": "outo_sk_<random-value>"
}
```

The plaintext key is returned only at creation time. A duplicate username returns HTTP `409`.

### `GET /v1/account/me`

Returns the authenticated user's identity and all workspaces owned by that user.

```bash
curl -s "$BASE_URL/v1/account/me" \
  -H "Authorization: Bearer $API_KEY"
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
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"experiments"}'
```

Response JSON, HTTP `200`:

```json
{
  "id": 2,
  "name": "experiments",
  "created_at": "2026-07-18T12:05:00+00:00"
}
```

A duplicate workspace name for the same user returns HTTP `409`.

### `GET /v1/workspaces`

Lists every workspace owned by the authenticated user.

```bash
curl -s "$BASE_URL/v1/workspaces" \
  -H "Authorization: Bearer $API_KEY"
```

Response JSON, HTTP `200`:

```json
[
  {
    "id": 1,
    "name": "default",
    "created_at": "2026-07-18T12:00:00+00:00"
  },
  {
    "id": 2,
    "name": "experiments",
    "created_at": "2026-07-18T12:05:00+00:00"
  }
]
```

## API keys

### `POST /v1/workspaces/{name}/keys`

Creates a key for a workspace owned by the authenticated user. The path `name` is the workspace name, not its numeric id.

Request JSON:

```json
{
  "label": "local development"
}
```

`label` is optional and defaults to an empty string.

```bash
curl -s -X POST "$BASE_URL/v1/workspaces/experiments/keys" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"label":"local development"}'
```

Response JSON, HTTP `200`:

```json
{
  "api_key": "outo_sk_<random-value>",
  "label": "local development",
  "workspace": "experiments"
}
```

The plaintext key is returned once. A key for a workspace the authenticated user does not own returns HTTP `404`.

### `GET /v1/workspaces/{name}/keys`

Lists key metadata for an owned workspace. It never returns plaintext keys or stored hashes.

```bash
curl -s "$BASE_URL/v1/workspaces/experiments/keys" \
  -H "Authorization: Bearer $API_KEY"
```

Response JSON, HTTP `200`:

```json
[
  {
    "id": 1,
    "label": "local development",
    "created_at": "2026-07-18T12:06:00+00:00",
    "revoked": false
  }
]
```

### `DELETE /v1/keys/{key_id}`

Revokes a key belonging to any workspace owned by the authenticated user. Revocation makes the key fail authentication. The key remains as metadata with `revoked: true`.

```bash
curl -s -X DELETE "$BASE_URL/v1/keys/1" \
  -H "Authorization: Bearer $API_KEY"
```

Response JSON, HTTP `200`:

```json
{
  "revoked": true
}
```

A key that is not owned by the user, or does not exist, returns HTTP `404`.

## Usage

### `GET /v1/usage`

Returns aggregate usage for the workspace associated with the current API key. Usage is grouped by model.

```bash
curl -s "$BASE_URL/v1/usage" \
  -H "Authorization: Bearer $API_KEY"
```

Response JSON, HTTP `200`:

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

For non-streaming proxy responses, accounting reads the upstream response's `usage.prompt_tokens` and `usage.completion_tokens` fields. Missing values are treated as zero. For streaming responses, the proxy adds `stream_options.include_usage: true` to the upstream request, forwards the stream, and records usage from the final usage-bearing SSE event when one is returned. Streaming accounting is best effort and never breaks the stream.

## Models

### `GET /v1/models`

Lists registered models in the OpenAI `list` shape. This is the registry exposed by outo-llms, not a direct listing from the engine.

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

## OpenAI-compatible proxy

### `POST /v1/chat/completions`

Forwards a chat completion request to the active engine. The JSON body must be an object with a registered `model` string. Other fields are forwarded to the upstream OpenAI-compatible engine.

```bash
curl -s "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "tinyllama",
    "messages": [
      {"role":"user","content":"What is 2 plus 2?"}
    ],
    "temperature": 0.2
  }'
```

The response is the upstream engine response. A typical response has this shape:

```json
{
  "id": "chatcmpl-example",
  "object": "chat.completion",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "2 plus 2 is 4."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 18,
    "completion_tokens": 8,
    "total_tokens": 26
  }
}
```

The exact id, text, and token counts come from the engine. A missing `model` returns HTTP `400`. An unregistered model returns HTTP `404` with code `model_not_found`. If the active engine is not installed or cannot start the selected model, the proxy returns HTTP `502`.

### `POST /v1/completions`

Forwards a legacy text completion request to the active engine. The body must contain a registered `model` string. Other fields are forwarded.

```bash
curl -s "$BASE_URL/v1/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "tinyllama",
    "prompt": "Complete this sentence: Local models are",
    "max_tokens": 32
  }'
```

The response is the upstream completion response, normally with a `choices` array and a `usage` object. Usage recording follows the same non-streaming and streaming rules as chat completions.

### Streaming

Set `"stream": true` in either proxy request. The proxy returns `text/event-stream` and forwards the upstream event bytes. It adds or replaces `stream_options.include_usage` with `true` so it can find final token counts for accounting.

```bash
curl -N "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "tinyllama",
    "messages": [{"role":"user","content":"Say hello."}],
    "stream": true
  }'
```

## Health and dashboard

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

Open HTML dashboard. It reports server status, active engine state, loaded model, workspace count, and registered model count, with links to `/docs` and `/healthz`.

```bash
curl -s "$BASE_URL/"
```

Open the same URL in a browser for the rendered dashboard.

## OpenAI SDK compatibility

The proxy uses OpenAI-compatible paths and request formats. Configure an OpenAI client with the outo-llms URL including `/v1` and an `outo_sk_...` key:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8611/v1",
    api_key="outo_sk_<key-created-by-signup>",
)

response = client.chat.completions.create(
    model="tinyllama",
    messages=[{"role": "user", "content": "Say hello."}],
)
print(response.choices[0].message.content)
```

For HTTPS, use `https://host:port/v1` and configure the client for the self-signed certificate as appropriate for your environment.
