# Security

outo-llms is designed for local or LAN deployments behind a single managed API server. This page summarizes the security boundaries it enforces, what it does not enforce, and how to operate it safely.

## API keys

The server issues keys with the `outo_sk_` prefix, followed by 24 URL-safe random bytes. The plaintext value is returned to the requester only at creation time. Setup does not create accounts. The first account comes from `POST /v1/account/signup`.

For each key, only its SHA-256 hex digest is stored. The SQLite `api_keys.key_hash` column is the unique identifier. The `revoked` flag deactivates a key without removing its metadata. Plaintext keys are never logged, never returned by listing endpoints, and never written to the action log.

Operations:

* Issue a key with `POST /v1/workspaces/{name}/keys`.
* List a workspace's keys with `GET /v1/workspaces/{name}/keys`. The response includes id, label, created timestamp, and revoked flag.
* Revoke a key with `DELETE /v1/keys/{key_id}`.

A revoked or unknown key returns HTTP `401` from the auth dependency in `server/deps.py`.

## Workspace boundaries

Every authenticated request resolves to one workspace context. The workspace owns its API keys, its usage rows, and any keys it issues. Cross-workspace access is not exposed. The workspace name is used in URL paths for key creation and listing because it is the natural user identifier, but key revocation is by numeric id and is checked against the workspace ownership.

The `default` workspace is created automatically during signup.

## Network binding

`setup` defaults to `0.0.0.0:443` with HTTPS enabled, so the server is reachable on the network right after a default install. To restrict the API to the local machine, pass `--host 127.0.0.1` (or another loopback address) to `setup`. With a public host the server is reachable by any host that can route to the listening port and any client with a valid `outo_sk_` key can call it. There is no built-in rate limit or IP allow list. Use an external reverse proxy or a host firewall for those controls if you need them.

The engine processes always bind to `127.0.0.1`. Their ports (`8612` by default for llama.cpp, `8613` for vLLM) are not the client API and should not be opened to other machines.

## HTTPS

`setup` generates a self-signed certificate and key in `data/certs/`. The key file is written with mode `0600`. The certificate's CN and subject alternative names cover `localhost`, `127.0.0.1`, the value of `server.domain` (or `--domain` to `setup`), and, when that value is a domain rather than an IP, the machine's auto-detected primary IP. Existing certificates are regenerated when `--domain` changes. When binding a port below `1024` on a POSIX system without root, setup runs `sudo setcap cap_net_bind_service=+ep <python>` after announcing the step and confirming (or auto-confirming with `--yes`); the action log records the exact command.

Browsers will warn about the self-signed certificate. The first visit to the dashboard prompts a one-time confirmation step in the browser; every visitor of the API over HTTPS will see the same warning. To proceed in development, either:

* Use `curl -k` to ignore the warning.
* Trust the certificate in your browser's or system's certificate store.
* Front the API with a reverse proxy that uses a trusted certificate for the public hostname.

A production deployment should put a reverse proxy in front of the loopback binding and terminate TLS there. The managed API does not implement ACME or any other certificate renewal.

## Firewall changes

`setup --open-port` may invoke `ufw allow <port>/tcp` or `firewall-cmd --permanent --add-port=<port>/tcp` followed by `firewall-cmd --reload`. Automatic firewall configuration is Linux-only.

The exact command is announced and then run without a shell. Without `--yes`, the system prompts for consent. With `--yes`, the prompt is skipped, but the announcement and the action log still record the action.

On Windows or macOS, setup explains that the port must be opened manually if needed. It does not invoke any system command.

## The action log

`logs/actions.log` is the auditable record of system-side actions. It contains timestamped lines written by the consent layer for setup steps, server lifecycle, engine lifecycle, certificate generation, firewall commands, and reset. It does not contain API request bodies, model output, or API key plaintext.

Inspect it with a normal tool:

```bash
tail -f "$(outo-llms status | awk -F': ' '/action log/ {print $2}' | tr -d ' ')"
```

You can also view it directly at:

```text
<data-dir>/logs/actions.log
```

## Hard rule on side effects

The implementation rule is: any code path that touches the system must go through `core/consent.py`. That includes subprocess invocation, firewall changes, file or directory changes outside the project tree, and any process control. The same rule applies to contributors. See [Development](development.md).

## Things outo-llms does not do

* It does not implement authentication for the dashboard at `/` or the health endpoint at `/healthz`. Both are open by design for local health checks.
* It does not implement rate limits, quota enforcement, or per-key rate metering. It only records token usage.
* It does not encrypt the SQLite database, the configuration file, or the action log. The platform filesystem permissions are the protection.
* It does not validate the TLS chain of upstream clients.
* It does not implement token rotation. Issue a new key and revoke the old one when you need to rotate.

## Recommended practices

* Treat `outo_sk_` keys as credentials. Store them in a password manager or in an environment variable, not in scripts shared with other users.
* Bind to `127.0.0.1` whenever possible. Use a reverse proxy if remote access is required, even when the default HTTPS deployment is in place.
* Run setup without `--yes` until you understand the announcements, then consider `--yes` for reproducible deployments.
* Periodically inspect the action log to confirm recorded behavior matches your expectations.
* Use `outo-llms reset` when you want a clean state. It is destructive and irreversible.