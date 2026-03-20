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

## Examples

### Run experiments

```bash
# Interactive mode — walks you through everything
autofoundry run

# Run a specific script
autofoundry run scripts/run_autoresearch.sh

# Specific GPU with multiple experiment runs
autofoundry run train.sh --gpu H100 --num 4

# Auto-select cheapest datacenter GPU with 80GB+ VRAM
autofoundry run train.sh --segment datacenter --min-vram 80 --auto

# Target a specific provider
autofoundry run train.sh --segment datacenter --min-vram 80 --provider runpod --auto
autofoundry run train.sh --segment datacenter --provider lambdalabs --auto
autofoundry run train.sh --segment workstation --provider vastai --auto
autofoundry run train.sh --segment datacenter --provider primeintellect --auto

# Attach a network volume (RunPod, Lambda Labs)
autofoundry run train.sh --volume my-data --provider runpod

# Resume a previous session
autofoundry run --resume <session-id>
```

### Browse GPU inventory

```bash
# Browse all available GPUs across providers
autofoundry inventory

# Filter by segment, VRAM, or GPU name
autofoundry inventory --segment datacenter --min-vram 80
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

See the [full documentation](docs/README.md) for writing experiment scripts, network volumes, resuming sessions, custom images, CLI reference, and architecture details.

## Requirements

- Python 3.11+
- SSH key pair (ed25519 or RSA)
- At least one provider API key (RunPod, Vast.ai, PRIME Intellect, or Lambda Labs)

## License

[MIT](LICENSE)
