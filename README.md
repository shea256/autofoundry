# Autofoundry

Run any ML experiment script across GPUs on multiple cloud providers with a single command.

Autofoundry is a CLI companion to [Karpathy's autoresearch](https://github.com/karpathy/autoresearch). Point it at a shell script, pick your GPU configuration, and it handles the rest: provisioning instances, distributing experiment runs, streaming results live, and producing a final metrics report.

## Supported Providers

- **RunPod** — Secure and Community cloud
- **Vast.ai** — Global GPU marketplace
- **PRIME Intellect** — Decentralized GPU network

## Quickstart

```bash
# Install
uv sync

# First run — configure API keys and SSH key path
uv run autofoundry your_experiment.sh

# Subsequent runs use saved config
uv run autofoundry your_experiment.sh --num-experiments 4 --gpu-type H100
```

On first run, Autofoundry walks you through configuring provider API keys and your SSH key path. Config is saved to `~/.config/autofoundry/config.toml`.

## How It Works

```
autofoundry train.sh --num-experiments 4 --gpu-type H100
```

1. **Query providers** — Fetches real-time GPU pricing and availability across all configured providers
2. **Select GPUs** — Interactive table lets you pick offers and quantities
3. **Provision** — Spins up instances in parallel, waits for SSH ready
4. **Execute** — Uploads your script, distributes experiments round-robin across instances, streams output live
5. **Report** — Parses metrics from script output and displays best/mean/worst summary
6. **Teardown** — Terminates all instances on completion (or Ctrl-C)

## Experiment Scripts

Your script runs in `/workspace` on a GPU instance with CUDA available. To report metrics back to Autofoundry, print a `---` delimiter followed by `key: value` lines:

```bash
#!/usr/bin/env bash
set -e

# ... your training code ...

echo "---"
echo "val_loss: 0.42"
echo "accuracy: 91.3"
echo "training_seconds: 300"
```

Autofoundry aggregates these across all experiment runs in the final report.

## Example: autoresearch

```bash
uv run autofoundry scripts/run_autoresearch.sh
```

This provisions an H100, clones autoresearch, trains a 50M parameter language model, and reports metrics including validation BPB, MFU, and throughput.

## CLI Options

```
autofoundry <script> [OPTIONS]

Arguments:
  script              Path to experiment shell script

Options:
  --num-experiments   Number of experiment runs (default: 1)
  --gpu-type          GPU type to search for (default: H100)
  --resume            Resume a previous session
```

## Architecture

```
cli.py           Entry point and interactive flow
planner.py       GPU offer querying and selection
provisioner.py   Instance lifecycle management
executor.py      SSH-based script upload and execution
reporter.py      Metrics aggregation and display
providers/       Provider API implementations (RunPod, Vast.ai, PRIME Intellect)
models.py        Data models (GpuOffer, InstanceConfig, InstanceInfo)
config.py        TOML configuration management
theme.py         Terminal styling and terminology
state.py         Session state persistence
```

## Requirements

- Python 3.11+
- SSH key pair (ed25519 or RSA)
- At least one provider API key (RunPod, Vast.ai, or PRIME Intellect)
