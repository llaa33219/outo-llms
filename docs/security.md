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

`setup` runs an mkcert-style local CA workflow. On the first setup with HTTPS, it creates a local root CA in `data/certs/`:

* `certs/ca.crt` is the public certificate of the outo-llms local CA. This is the one file clients need.
* `certs/ca.key` is the CA's private key, written with mode `0600` and never written to logs or copied anywhere by the tool.

The CA is then used to sign a server certificate (`certs/server.crt` and `certs/server.key`, key mode `0600`) whose CN and subject alternative names cover `localhost`, `127.0.0.1`, the value of `server.domain` (or `--domain` to `setup`), and, when that value is a domain rather than an IP, the machine's auto-detected primary IP.

The CA is kept across runs. It is reused when the domain changes and when the server certificate is regenerated, so clients only ever install one file: `ca.crt`. The server certificate is regenerated when the domain or IP changes or when its remaining validity drops below 30 days. The CA itself is valid for 10 years. The deployment target is LAN or private-IP HTTPS, so a public CA like Let's Encrypt is not applicable to this workflow.

When binding a port below `1024` on a POSIX system without root, setup runs `sudo setcap cap_net_bind_service=+ep <python>` after announcing the step and confirming (or auto-confirming with `--yes`); the action log records the exact command.

### Trusting the CA on the server itself

`setup` offers a trust-store step. The flag is `--trust-store/--no-trust-store`; the prompt defaults to yes, and `--yes` accepts yes. On supported Linux systems, when not running as root, setup runs the steps through `sudo` after announcing and confirming each one, and records the exact commands in the action log:

* Debian, Ubuntu, and derivatives: copy `certs/ca.crt` to `/usr/local/share/ca-certificates/outo-llms-local-ca.crt` with mode `0644`, then run `sudo update-ca-certificates`.
* Fedora, RHEL, CentOS, and derivatives: copy `certs/ca.crt` to `/etc/pki/ca-trust/source/anchors/outo-llms-local-ca.crt`, then run `sudo update-ca-trust`.

After this step runs successfully, `curl https://<server-ip>/` and browsers on the same machine trust the server with no warning and no `-k` flag.

On non-Linux systems, or on Linux distributions the wizard does not recognize, setup prints manual instructions instead of running anything. The `ca.crt` file is still generated and the setup still announces and logs that fact.

### Trusting the CA on client machines

On machines other than the server, install the same `certs/ca.crt` file into the system or browser trust store. Once installed, those clients also trust the server certificate with no warning. The exact steps depend on the operating system:

* **Linux.** Copy `ca.crt` into `/usr/local/share/ca-certificates/` (Debian/Ubuntu) or `/etc/pki/ca-trust/source/anchors/` (Fedora/RHEL), then run `sudo update-ca-certificates` or `sudo update-ca-trust` respectively. Use the same paths setup would have used on the server.
* **macOS.** Open Keychain Access, drag `ca.crt` into the System keychain, then set "Always Trust" for that certificate. From a terminal, the equivalent command is `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.crt`.
* **Windows.** Open `certlm.msc`, navigate to Trusted Root Certification Authorities, and import `ca.crt`. From an elevated command prompt, `certutil -addstore -f ROOT ca.crt` does the same.
* **Firefox.** Firefox uses its own certificate store rather than the system one. Open Settings, go to Privacy & Security, scroll to Certificates, click View Certificates, choose Your Certificates or Authorities as appropriate, and import `ca.crt`. Trust the CA for websites.

Until the CA is installed on a client, `curl` still needs `-k` and browsers still show the certificate warning. Installing `ca.crt` once is enough for that client, because the CA is reused across server-certificate regenerations.

### Treating the CA private key as a secret

`ca.key` never leaves the server under normal operation, and it is written with mode `0600`. Anyone who obtains the file can mint additional certificates that browsers and `curl` will trust for any host on this LAN. Treat `ca.key` like a password: do not copy it, do not commit it, and rotate the CA (delete `ca.crt` and `ca.key`, then re-run setup) if it is exposed.

A production deployment that needs a publicly trusted certificate should put a reverse proxy in front of the loopback binding and terminate TLS there. The managed API does not implement ACME or any other certificate renewal.

## Firewall changes

`setup --open-port` may invoke `sudo ufw allow <port>/tcp` or `sudo firewall-cmd --permanent --add-port=<port>/tcp` followed by `sudo firewall-cmd --reload` (the `sudo` prefix is used when outo-llms is not running as root). Automatic firewall configuration is Linux-only.

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

* It does not implement authentication for the web GUI assets at `/` or the health endpoint at `/healthz`. Both are open by design: the assets are static files and every `/v1` call the GUI makes still requires a valid API key.
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