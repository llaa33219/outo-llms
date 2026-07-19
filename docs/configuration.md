# Configuration and filesystem

outo-llms keeps its configuration and runtime data in platformdirs locations. On a typical Linux installation:

```text
config directory: ~/.config/outo-llms/
data directory:   ~/.local/share/outo-llms/
```

The exact base directories can vary by operating system because they come from `platformdirs`.

## `config.json`

The configuration file is:

```text
<config-dir>/config.json
```

Its complete shape is:

```json
{
  "engine": {
    "extra_args": [],
    "name": "llamacpp"
  },
  "server": {
    "domain": "",
    "host": "0.0.0.0",
    "https": true,
    "port": 443
  }
}
```

The fields are:

| Path | Type | Default | Meaning |
| --- | --- | --- | --- |
| `server.host` | string | `0.0.0.0` | Interface where the managed API server listens. |
| `server.port` | integer | `443` | Port where the managed API server listens. |
| `server.https` | boolean | `true` | Whether Uvicorn serves HTTPS using the generated certificate and key. |
| `server.domain` | string | `""` | Domain or IP used as the certificate CN/SAN. When empty, the certificate falls back to the auto-detected primary IP (or `localhost` if detection fails). Existing certificates are regenerated when the value changes. |
| `engine.name` | string | `llamacpp` | Active engine adapter, either `llamacpp` or `vllm`. |
| `engine.extra_args` | array of strings | `[]` | Extra command-line arguments appended to the active engine's serve command. |

Missing files and missing keys fall back to these defaults when the configuration is loaded. `setup` writes all fields. `engine use` changes `engine.name`. `setup` with a `--domain` value updates `server.domain` and regenerates the certificate on the next start.

### `engine.extra_args`

The values in this list are passed directly to the selected engine process after the model arguments. They are not shell commands and are not parsed by outo-llms. Use only flags supported by the selected upstream server.

For example, a configuration may contain:

```json
{
  "engine": {
    "extra_args": ["--verbose"],
    "name": "llamacpp"
  },
  "server": {
    "domain": "203.0.113.10",
    "host": "0.0.0.0",
    "https": true,
    "port": 443
  }
}
```

Keep the configuration valid JSON. The CLI is the normal way to create it.

## Directory layout

The paths module is the single source of truth for filesystem locations:

```text
<config-dir>/
└── config.json

<data-dir>/
├── outo-llms.db
├── server.pid
├── engines/
│   ├── llamacpp/
│   │   ├── venv/
│   │   └── INSTALLED
│   ├── llamacpp.pid
│   ├── llamacpp.port
│   ├── llamacpp.model
│   ├── vllm/
│   │   ├── venv/
│   │   └── INSTALLED
│   ├── vllm.pid
│   ├── vllm.port
│   └── vllm.model
├── models/
├── certs/
│   ├── ca.crt
│   ├── ca.key
│   ├── server.crt
│   └── server.key
└── logs/
    ├── server.log
    ├── engine-llamacpp.log
    ├── engine-vllm.log
    └── actions.log
```

The exact files present depend on which engines and HTTPS options you use.

### What each location holds

* `outo-llms.db` is the SQLite database. It contains users, workspaces, API key hashes, the model registry, and usage records.
* `server.pid` records the detached API server process id.
* `engines/` contains isolated engine environments, installation markers, and the active engine's PID, port, and model state files.
* `models/` is created as part of the managed data layout. The model registry itself is stored in SQLite. The upstream engine and its model-loading libraries determine where downloaded model caches are placed.
* `certs/` contains the local CA and the server certificate when HTTPS is enabled. `ca.crt` is the public certificate of the outo-llms local CA, valid for 10 years and shared across server-certificate regenerations. `ca.key` is the CA's mode `0600` private key and never leaves the server under normal operation; it is the only secret that can mint trusted certificates for this LAN. `server.crt` and `server.key` are the server certificate and its mode `0600` private key, signed by the CA. The server certificate is regenerated when the domain or IP changes or when its remaining validity drops below 30 days.
* `logs/server.log` receives detached API server output.
* `logs/engine-<name>.log` receives output from an engine subprocess.
* `logs/actions.log` contains timestamped action records written by the explicitness machinery.

## Creation and reset

`outo-llms setup` creates both base directories, the child directories, configuration, database, and the selected engine environment. The server also initializes the database on startup if necessary.

`outo-llms reset` stops the server and current engine, then removes the complete data and config directories. This removes the database, registry, engine environments, state files, certificates, logs, and `config.json`. It returns the installation to a fresh state. See [CLI reference](cli.md) and [Security](security.md) before using it.
