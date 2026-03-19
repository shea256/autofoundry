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
uv tool install autofoundry
```

Then run:

```bash
autofoundry run
```

On first run, Autofoundry walks you through configuring provider API keys, SSH key path, minimum download bandwidth (default 5000 Mbps — filters out slow Vast.ai hosts), and HuggingFace token. Config is saved to `~/.config/autofoundry/config.toml`.

## How It Works

```
autofoundry run
```

1. **Query providers** — Fetches real-time GPU pricing and availability across all configured providers
2. **Select GPUs** — Interactive tier selection (consumer/workstation/datacenter) or specific GPU name, then pick offers and quantities
3. **Provision** — Spins up instances in parallel, waits for SSH ready
4. **Execute** — Uploads your script, distributes experiments round-robin across instances, streams output live
5. **Report** — Parses metrics from script output and displays best/mean/worst summary
6. **Teardown** — Terminates all instances on completion (or Ctrl-C)

## Examples

### Run experiments

```bash
# Interactive mode — walks you through everything
autofoundry run

# Run a specific script
autofoundry run scripts/run_autoresearch.sh

# Specific GPU with multiple experiment runs
autofoundry run train.sh --gpu H100 --num 4

# Auto-select cheapest offer in a tier
autofoundry run train.sh --tier datacenter-80gb+ --auto

# Target a specific provider
autofoundry run train.sh --tier datacenter-80gb+ --provider runpod --auto
autofoundry run train.sh --tier datacenter-80gb+ --provider lambdalabs --auto
autofoundry run train.sh --tier datacenter-80gb+ --provider vastai --auto
autofoundry run train.sh --tier datacenter-80gb+ --provider primeintellect --auto

# Attach a network volume (RunPod, Lambda Labs)
autofoundry run train.sh --volume my-data --provider runpod

# Resume a previous session
autofoundry run --resume <session-id>
```

### Browse GPU inventory

```bash
# Browse all available GPUs across providers
autofoundry inventory

# Filter by tier or GPU name
autofoundry inventory --tier datacenter-80gb+
autofoundry inventory --gpu A100
```

### Configure

```bash
# Interactive setup for API keys, SSH key, and defaults
autofoundry config
```

### Manage volumes

```bash
# List volumes across providers
autofoundry volumes list

# Create a new volume
autofoundry volumes create --name my-data --provider runpod
```

### Monitor and manage sessions

```bash
# Show all sessions
autofoundry status

# Show a specific session
autofoundry status <session-id>

# View metrics from most recent run
autofoundry results

# Terminate instances for a session
autofoundry teardown <session-id>
```

See the [guides](docs/guides.md) for writing experiment scripts, network volumes, resuming sessions, custom images, CLI reference, and architecture details.

## Requirements

- Python 3.11+
- SSH key pair (ed25519 or RSA)
- At least one provider API key (RunPod, Vast.ai, PRIME Intellect, or Lambda Labs)

## License

[MIT](LICENSE)
