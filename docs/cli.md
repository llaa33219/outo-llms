# CLI reference

The package installs one console script, `outo-llms`. Running it without a subcommand shows help. The commands below are the complete command tree in version `0.2.6`.

## `outo-llms setup`

```text
outo-llms setup [OPTIONS]
```

Runs the setup wizard. It creates the configuration and data directories, writes `config.json`, initializes SQLite, creates an isolated engine virtual environment, installs that engine's requirements, creates a local CA and signs a server certificate for the configured domain or IP, optionally installs that CA into the system trust store, opens the server port in a supported Linux firewall, and starts the API server in the background.

Options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--engine`, `-e` | `llamacpp` (prompt or `--yes`) | Engine to install: `llamacpp` or `vllm`. |
| `--host` | `0.0.0.0` | Interface for the API server. |
| `--port`, `-p` | `443` | API server port. |
| `--domain` | auto-detected primary IP, falling back to `localhost` | Domain or IP for the HTTPS certificate. Detected locally without sending any traffic. The certificate's SANs cover `localhost`, `127.0.0.1`, the chosen value, and, when a domain is given, the detected primary IP. The server certificate is regenerated when the domain changes or its remaining validity drops below 30 days; the CA itself is reused. |
| `--https` / `--no-https` | enabled (prompt default yes, `--yes` accepts yes) | Serve with a server certificate signed by the local outo-llms CA. |
| `--trust-store` / `--no-trust-store` | enabled (prompt default yes, `--yes` accepts yes) | Install `certs/ca.crt` into the system trust store on supported Linux systems. Non-Linux or unrecognized distributions print manual instructions instead. |
| `--open-port` / `--no-open-port` | enabled (prompt default yes, `--yes` accepts yes) | Open the server port in the system firewall when supported (Linux only). |
| `--yes`, `-y` | `false` | Do not prompt. Accept setup defaults and keep announcing and logging each action. |

Without `--yes`, setup asks for the engine when it is not supplied, asks whether to use HTTPS (default yes), asks whether to install the CA into the system trust store (default yes), asks whether to open the firewall port (default yes), prompts for the certificate domain, and asks for confirmation of the displayed plan. If configuration already exists, it asks whether to reconfigure. With `--yes` and an existing configuration, setup does not reconfigure and exits while keeping the existing configuration.

Privileged ports: when the chosen port is below `1024` on a POSIX system and outo-llms is not running as root, setup grants the Python interpreter permission to bind low ports with `sudo setcap cap_net_bind_service=+ep <python>`. The step is announced in the plan, confirmed unless `--yes` is set, and recorded in the action log. If the step fails or is declined, setup warns that the server may not bind the configured port and suggests picking a port above `1024`.

Examples:

```bash
# Interactive setup
outo-llms setup

# Fresh, non-interactive setup with the server-first defaults (llama.cpp, 0.0.0.0:443, HTTPS, firewall)
outo-llms setup --engine llamacpp --yes

# Non-interactive loopback setup that opts out of HTTPS and the firewall
outo-llms setup --engine llamacpp --no-https --no-open-port --yes

# Interactive setup with a specific domain and engine
outo-llms setup --host 0.0.0.0 --port 443 --domain api.example.com --engine vllm
```

System effects include creating directories under the platformdirs config and data locations, writing configuration and database files, creating a venv, running pip inside that venv, creating the local CA and signing the server certificate, installing `ca.crt` into the system trust store via sudo on supported Linux systems (`update-ca-certificates` or `update-ca-trust`), running the Linux firewall tool via sudo when not root (`ufw` or `firewalld`), running `sudo setcap` when binding a privileged port, and starting a detached server process. Every setup step is announced. The setup plan and action log show the paths, selected values, and the exact commands run.

## `outo-llms models`

```text
outo-llms models [COMMAND]
```

Manages the model registry in the local SQLite database. These commands do not download model weights. The engine downloads weights when the first request needs the model.

### `outo-llms models add`

```text
outo-llms models add NAME [OPTIONS]
```

Registers one model. `NAME` is the model identifier clients use in API requests.

Options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--source`, `-s` | `NAME` | Hugging Face repository id or a local `.gguf` path. For llama.cpp, a `repo:file` source selects a file in a Hugging Face repository. |
| `--kind`, `-k` | guessed from source | Model kind, either `hf` or `gguf`. If omitted, a source ending in `.gguf` or an existing path is treated as `gguf`; otherwise it is treated as `hf`. |

Examples:

```bash
# Hugging Face model for vLLM
outo-llms models add tinyllama \
  --source 'TinyLlama/TinyLlama-1.1B-Chat-v1.0' \
  --kind hf

# GGUF file selected from a Hugging Face repository for llama.cpp
outo-llms models add tinyllama \
  --source 'TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF:Q4_K_M' \
  --kind gguf

# Local GGUF path, with kind inferred from the path
outo-llms models add local-model --source /path/to/model.gguf
```

The command initializes the database and inserts one registry row. Model names must be unique. A duplicate name or invalid kind exits with an error.

### `outo-llms models list`

```text
outo-llms models list
```

Prints the registered model name, kind, source, and creation timestamp. It initializes the database if needed and changes no registry data.

```bash
outo-llms models list
```

### `outo-llms models remove`

```text
outo-llms models remove NAME
```

Asks for confirmation, then removes the named registry row. It does not delete downloaded weights or engine environments. If the name is not registered, it reports that fact.

```bash
outo-llms models remove tinyllama
```

## `outo-llms engine`

```text
outo-llms engine [COMMAND]
```

Manages the two registered engine adapters and the active engine configuration.

### `outo-llms engine list`

```text
outo-llms engine list
```

Lists `llamacpp` and `vllm`, whether each is installed, and which one is active. It reads engine marker files and the current configuration.

```bash
outo-llms engine list
```

### `outo-llms engine use`

```text
outo-llms engine use NAME
```

Selects an installed engine as active. `NAME` must be `llamacpp` or `vllm`, and the engine must already have an isolated venv and `INSTALLED` marker.

```bash
outo-llms engine use vllm
```

This writes `engine.name` in `config.json` and logs the selection. It does not install the engine. A later inference request uses the selected adapter. See [Engines](engines.md) for model-kind compatibility.

### `outo-llms engine install`

```text
outo-llms engine install [NAME]
```

Creates or recreates the selected engine's isolated venv, upgrades pip in that venv, installs the adapter requirements, and writes its `INSTALLED` marker. If `NAME` is omitted, the active engine is installed.

```bash
# Install the active engine
outo-llms engine install

# Install vLLM without selecting it
outo-llms engine install vllm
```

The installed requirements are `llama-cpp-python[server]>=0.2.90` for llama.cpp and `vllm>=0.6` for vLLM. The command streams pip output and announces the environment and package installation.

### `outo-llms engine status`

```text
outo-llms engine status
```

Shows the active engine's `installed`, `running`, `pid`, `model`, `port`, and internal `base_url` values. It also shows API server running state and PID.

```bash
outo-llms engine status
```

## Server lifecycle commands

### `outo-llms start`

```text
outo-llms start
```

Starts the configured API server as a detached `python -m outo_llms.server` process, records its PID, and appends output to `server.log`. It fails if the server is already running.

```bash
outo-llms start
```

### `outo-llms stop`

```text
outo-llms stop
```

Stops the process recorded in `server.pid`, removes that PID file, and reports whether a process was stopped. It does not remove configuration, database, models, engine environments, or logs.

```bash
outo-llms stop
```

### `outo-llms restart`

```text
outo-llms restart
```

Stops the configured API server and starts it again. Engine state is managed separately by the engine manager.

```bash
outo-llms restart
```

### `outo-llms status`

```text
outo-llms status
```

Shows server state, host, port, HTTPS setting, domain, the formatted base URL, active engine state, and key paths including the configuration file, data directory, action log, and server log. HTTPS on port `443` is printed without the port suffix so the URL stays clean.

```bash
outo-llms status
```

## `outo-llms reset`

```text
outo-llms reset
```

Stops the API server and current engine, then deletes both the complete outo-llms data directory and configuration directory. It asks for two independent confirmations. There is no `--yes` option for reset.

```bash
outo-llms reset
```

The reset removes the database, model registry, engine virtual environments, engine state, certificates, logs, and `config.json`. It cannot be undone. The reset action is announced and logged before the directories are removed.

## `outo-llms version`

```text
outo-llms version
```

Prints the installed package version.

```bash
outo-llms version
```
