# Autofoundry

Run any ML experiment script across GPUs on multiple cloud providers with a single command.

<p align="center">
  <img src="assets/autofoundry-demo.gif" alt="Autofoundry CLI demo" width="620">
</p>

Autofoundry is a CLI companion to [Karpathy's autoresearch](https://github.com/karpathy/autoresearch). Point it at a shell script, pick your GPU configuration, and it handles the rest: provisioning instances, distributing experiment runs, streaming results live, and producing a final metrics report.

## Supported Providers

- **[RunPod](https://www.runpod.io/)** — Secure and Community cloud
- **[Vast.ai](https://vast.ai/)** — Global GPU marketplace
- **[PRIME Intellect](https://www.primeintellect.ai/)** — Decentralized GPU network
- **[Lambda Labs](https://lambdalabs.com/)** — On-demand cloud GPUs

## Quickstart

```bash
git clone https://github.com/autofoundry/autofoundry.git
cd autofoundry
uv pip install -e .
autofoundry run scripts/run_autoresearch.sh -g H100 --provider runpod --auto
```

On first run, Autofoundry walks you through configuring provider API keys, SSH key path, default GPU type, minimum download bandwidth (default 5000 Mbps — filters out slow Vast.ai hosts), and HuggingFace token. Config is saved to `~/.config/autofoundry/config.toml`.

If you already have your own experiment scripts, you can install just the CLI:

```bash
pip install autofoundry
```

## How It Works

```
autofoundry run train.sh --num 4 --gpu H100
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

Run [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) on any provider:

```bash
autofoundry run scripts/run_autoresearch.sh -g H100 --provider runpod --region US --auto
autofoundry run scripts/run_autoresearch.sh -g H100 --provider lambdalabs --region US --auto
autofoundry run scripts/run_autoresearch.sh -g H100 --provider vastai --auto
autofoundry run scripts/run_autoresearch.sh -g H100 --provider primeintellect --auto
```

This provisions an H100, clones autoresearch, trains a 50M parameter language model, and reports metrics including validation BPB, MFU, and throughput.

## Network Volumes

Attach persistent storage so dependencies survive across runs:

```bash
# First run — creates volume, installs deps to /workspace
autofoundry run scripts/run_autoresearch.sh --volume my-workspace --provider runpod

# Second run — finds existing volume, skips install
autofoundry run scripts/run_autoresearch.sh --volume my-workspace --provider runpod
```

Supported on RunPod and Lambda Labs.

## Resuming Sessions

If a session is interrupted, resume it to restart stopped instances and run remaining experiments:

```bash
autofoundry run scripts/run_autoresearch.sh --resume <session-id>
```

On resume, the script detects the existing venv (at `/workspace/.autoresearch_venv`) and skips all setup — no image pull, no pip install. Setup takes seconds instead of minutes.

## Custom Images

Override the default provider image with `--image`:

```bash
# Use a pre-built autoresearch image (skips torch download)
autofoundry run scripts/run_autoresearch.sh --image runpod/autoresearch:1.0.2-cuda1281-ubuntu2204

# Or declare per-provider images in your script header:
# autofoundry:image:runpod=runpod/autoresearch:1.0.2-cuda1281-ubuntu2204
# autofoundry:image:vastai=shea256/autoresearch:latest
```

When the image name contains "autoresearch", the script inherits system torch and only installs lightweight dependencies.

## CLI Reference

```
autofoundry run [SCRIPT] [OPTIONS]

Arguments:
  script              Path to experiment shell script (prompted if omitted)

Options:
  --num, -n           Number of experiment runs (default: 1)
  --gpu, -g           GPU type to search for (default: H100)
  --provider, -p      Provider filter (e.g. runpod, vastai, primeintellect, lambdalabs)
  --region            Region filter (e.g. US, EU)
  --resume, -r        Resume a previous session
  --volume, -v        Network volume name (RunPod, Lambda Labs)
  --image, -i         Docker image override (e.g. runpod/autoresearch:latest)
  --auto              Auto-select cheapest offer, no prompts

autofoundry config                          Configure provider API keys
autofoundry inventory [-g GPU]              Browse GPU inventory
autofoundry volumes list                    List network volumes
autofoundry volumes create [--name] [--provider] [--size] [--region]
                                            Create a new network volume
autofoundry status [OP_ID]                  Show operation status
autofoundry results [OP_ID]                 Show experiment metrics
autofoundry teardown OP_ID                  Terminate instances
```

## Architecture

```
cli.py           Entry point — run, config, inventory, volumes, status, results, teardown
planner.py       GPU offer querying and selection
provisioner.py   Instance lifecycle management
executor.py      SSH-based script upload and execution
reporter.py      Metrics aggregation and display
providers/       Provider API implementations
models.py        Data models (GpuOffer, InstanceConfig, VolumeInfo, Session)
config.py        TOML configuration management
state.py         SQLite session persistence
theme.py         Terminal styling
```

## Requirements

- Python 3.11+
- SSH key pair (ed25519 or RSA)
- At least one provider API key (RunPod, Vast.ai, PRIME Intellect, or Lambda Labs)

## License

[MIT](LICENSE)
