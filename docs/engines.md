# Engines

outo-llms currently registers two engine adapters:

* `llamacpp`, displayed as llama.cpp through `llama-cpp-python`.
* `vllm`, displayed as vLLM.

The API server is the only client-facing process. Each engine binds to `127.0.0.1` and is reached through the managed proxy.

## Choosing an engine

| Engine | Best fit | Model kind | Default internal port |
| --- | --- | --- | --- |
| llama.cpp | CPU-friendly local inference and GGUF models | `gguf` | `8612` |
| vLLM | GPU-backed inference, Hugging Face models, and higher throughput | `hf` | `8613` |

llama.cpp can run on a CPU. vLLM effectively needs a compatible NVIDIA GPU for normal use.

The active engine is selected in `config.json`. Setup defaults to `llamacpp`.

## Isolation model

Each engine gets a separate virtual environment at:

```text
<data-dir>/engines/<engine>/venv/
```

For example:

```text
<data-dir>/engines/llamacpp/venv/
<data-dir>/engines/vllm/venv/
```

`outo-llms engine install` creates the venv with the Python interpreter running the CLI, upgrades pip inside that venv, and installs only the selected adapter requirements there. The existing Python environment is not used as the engine runtime and is not modified by engine package installation.

The engine requirements are:

* llama.cpp: `llama-cpp-python[server]>=0.2.90`
* vLLM: `vllm>=0.6`

Engine processes are detached by the manager, have their output redirected to an engine log, and always bind to loopback. Clients never connect directly to the engine port.

## Installing and selecting an engine

List available engines and their installed state:

```bash
outo-llms engine list
```

Install the active engine:

```bash
outo-llms engine install
```

Install a named engine without selecting it:

```bash
outo-llms engine install vllm
```

Select an installed engine:

```bash
outo-llms engine use vllm
```

`engine use` writes the active engine name to `config.json`. It does not install an engine. The selected engine must already be installed. A request then uses that adapter, provided the registered model kind matches it.

Inspect both server and active engine state:

```bash
outo-llms engine status
```

## Model source formats

The model registry stores a client-facing name, a source string, and a kind. The active adapter checks the kind before starting.

### llama.cpp and GGUF

llama.cpp supports `kind: "gguf"`. The source can be:

1. A local `.gguf` path. The adapter passes it as `--model <path>`.
2. A Hugging Face repository and filename separated by one colon. The adapter passes the parts as `--hf_model_repo_id <repo>` and `--hf_model_file <filename>`.
3. A Hugging Face repository id without a colon. The adapter passes it as `--hf_model_repo_id <repo>`.

Examples:

```bash
outo-llms models add local-model \
  --source /models/tinyllama.gguf \
  --kind gguf

outo-llms models add tinyllama \
  --source 'TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF:Q4_K_M' \
  --kind gguf
```

A local path is detected with the filesystem. If the source ends in `.gguf` or points to an existing path, `models add` guesses `gguf` when `--kind` is omitted.

### vLLM and Hugging Face

vLLM supports `kind: "hf"`. The source is a Hugging Face repository id and is passed as the `--model` value to vLLM.

```bash
outo-llms models add tinyllama \
  --source 'TinyLlama/TinyLlama-1.1B-Chat-v1.0' \
  --kind hf
```

If a model is gated, provide `HF_TOKEN` in the environment inherited by the server and engine process before the first request. See [Installation](installation.md).

## Serving arguments

The adapters launch OpenAI-compatible upstream servers with their isolated venv interpreter.

llama.cpp is started as `python -m llama_cpp.server` with `--host 127.0.0.1`, an available port starting at `8612`, and the model-specific flags described above.

vLLM is started as `python -m vllm.entrypoints.openai.api_server` with `--host 127.0.0.1`, an available port starting at `8613`, and `--model <source>`.

Any strings in `engine.extra_args` from `config.json` are appended to the selected engine's command line after the model arguments. The engine adapter does not interpret these arguments.

## One model at a time

The active engine serves one registered model at a time. The first request for a model starts that model. If a later request names a different registered model, `EngineManager.ensure_running()` stops the current engine process, selects a free port at or above the adapter's default, starts the new model, and waits for its upstream `/v1/models` endpoint to respond.

A request for the same model reuses the running process. The managed API server remains on its configured host and port while the internal engine port can change if the preferred port is occupied.

## Engine state and logs

State files are stored directly under the engine directory:

```text
<data-dir>/engines/<name>/INSTALLED
<data-dir>/engines/<name>.pid
<data-dir>/engines/<name>.port
<data-dir>/engines/<name>.model
```

The engine output log is:

```text
<data-dir>/logs/engine-<name>.log
```

For example, llama.cpp writes to `logs/engine-llamacpp.log`. If an engine exits during startup or does not become ready, the CLI and proxy report this log path.

The [configuration reference](configuration.md) documents `engine.name` and `engine.extra_args`. The [architecture guide](architecture.md) explains how the manager fits into request handling.
