# Installation

## Requirements

* Python 3.10 or newer.
* A supported Python environment for the CLI. `outo-llms` itself is published on PyPI.
* Network access when installing an engine and when a model must be downloaded.
* Enough disk space for the selected engine virtual environment and model weights.

The package depends on Typer, Rich, FastAPI, Uvicorn, HTTPX, platformdirs, cryptography, and Pydantic. Engine packages are installed separately by `outo-llms setup` or `outo-llms engine install`.

## Install the CLI

`pipx` is recommended because it keeps the command-line application isolated from other Python packages while leaving outo-llms able to create its own engine environments.

```bash
pipx install outo-llms
```

If you prefer a regular Python environment, install from PyPI with `pip`:

```bash
python -m pip install outo-llms
```

Confirm the installed version:

```bash
outo-llms version
```

The current package version is `0.3.1`.

## Operating system notes

Linux is the primary operational environment, especially when you want setup to configure a firewall. On Linux, setup can use `ufw` or `firewall-cmd` when the selected `--open-port` option is enabled. The exact firewall command is announced before it runs and requires consent unless setup uses `--yes`.

Automatic firewall configuration is only supported on Linux. On other systems, setup explains that the server port must be opened manually if you need access from another machine. Firewall configuration is offered by default (the prompt defaults to yes) and can be declined or skipped with `--no-open-port`.

The server binds to `0.0.0.0:443` with HTTPS by default, so the firewall prompt and a possible privileged-port `sudo setcap` step are part of the normal flow. For a loopback-only installation, pass `--host 127.0.0.1` (and choose a port above 1024, e.g. `--port 8611`). See [Security](security.md) for the implications of each binding.

## Hardware notes

llama.cpp can run on a CPU and is the practical default for CPU-friendly deployments. It serves GGUF models.

vLLM is intended for GPU-backed deployments and effectively requires a compatible NVIDIA GPU for normal use. It serves Hugging Face model repositories and is the better choice when you need higher throughput from supported GPU hardware.

Engine installation happens in a separate virtual environment under the outo-llms data directory. It does not modify the environment where you installed the CLI. Engine installation can still download a large number of packages, so allow time and disk space for it.

## Access to gated Hugging Face models

Some Hugging Face repositories require authentication. If the selected model is gated, set `HF_TOKEN` in the environment inherited by the server and engine process before the model is downloaded:

```bash
export HF_TOKEN="hf_your_token"
```

outo-llms does not put this token in `config.json`, the SQLite database, or the action log. The engine subprocess inherits the environment of the process that starts it. Follow the model publisher's access requirements.

## Next step

Run the [quickstart](quickstart.md). It uses llama.cpp with a small GGUF model and the default local HTTP binding.
