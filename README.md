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
uv run autofoundry run scripts/run_autoresearch.sh --provider runpod --auto
```

On first run, Autofoundry walks you through configuring provider API keys, SSH key path, default GPU type, minimum download bandwidth (default 5000 Mbps — filters out slow Vast.ai hosts), and HuggingFace token. Config is saved to `~/.config/autofoundry/config.toml`.

If you already have your own experiment scripts, you can install just the CLI:

```bash
pip install autofoundry
```

## How It Works

```
autofoundry run train.sh --num 4
```

1. **Query providers** — Fetches real-time GPU pricing and availability across all configured providers
2. **Select GPUs** — Interactive table lets you pick offers and quantities
3. **Provision** — Spins up instances in parallel, waits for SSH ready
4. **Execute** — Uploads your script, distributes experiments round-robin across instances, streams output live
5. **Report** — Parses metrics from script output and displays best/mean/worst summary
6. **Teardown** — Terminates all instances on completion (or Ctrl-C)

## Example: autoresearch

Run [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) on any provider:

```bash
autofoundry run scripts/run_autoresearch.sh --provider runpod --region US --auto
autofoundry run scripts/run_autoresearch.sh --provider lambdalabs --region US --auto
autofoundry run scripts/run_autoresearch.sh --provider vastai --auto
autofoundry run scripts/run_autoresearch.sh --provider primeintellect --auto
```

This provisions an H100, clones autoresearch, trains a 50M parameter language model, and reports metrics including validation BPB, MFU, and throughput.

See the [guides](docs/guides.md) for writing experiment scripts, network volumes, resuming sessions, custom images, CLI reference, and architecture details.

## Requirements

- Python 3.11+
- SSH key pair (ed25519 or RSA)
- At least one provider API key (RunPod, Vast.ai, PRIME Intellect, or Lambda Labs)

## License

[MIT](LICENSE)
