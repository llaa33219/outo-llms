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
    "host": "127.0.0.1",
    "https": false,
    "port": 8611
  }
}
```

The fields are:

| Path | Type | Default | Meaning |
| --- | --- | --- | --- |
| `server.host` | string | `127.0.0.1` | Interface where the managed API server listens. |
| `server.port` | integer | `8611` | Port where the managed API server listens. |
| `server.https` | boolean | `false` | Whether Uvicorn serves HTTPS using the generated certificate and key. |
| `engine.name` | string | `llamacpp` | Active engine adapter, either `llamacpp` or `vllm`. |
| `engine.extra_args` | array of strings | `[]` | Extra command-line arguments appended to the active engine's serve command. |

Missing files and missing keys fall back to these defaults when the configuration is loaded. `setup` writes all fields. `engine use` changes `engine.name`.

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
    "host": "127.0.0.1",
    "https": false,
    "port": 8611
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
* `certs/` contains `server.crt` and the mode `0600` private key `server.key` when HTTPS is enabled.
* `logs/server.log` receives detached API server output.
* `logs/engine-<name>.log` receives output from an engine subprocess.
* `logs/actions.log` contains timestamped action records written by the explicitness machinery.

## Creation and reset

`outo-llms setup` creates both base directories, the child directories, configuration, database, and the selected engine environment. The server also initializes the database on startup if necessary.

`outo-llms reset` stops the server and current engine, then removes the complete data and config directories. This removes the database, registry, engine environments, state files, certificates, logs, and `config.json`. It returns the installation to a fresh state. See [CLI reference](cli.md) and [Security](security.md) before using it.
