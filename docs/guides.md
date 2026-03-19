# Guides

## Writing Experiment Scripts

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
  --gpu, -g           Specific GPU type (e.g. H100, RTX 4090)
  --segment, -s       GPU segment (consumer, workstation, datacenter)
  --min-vram          Minimum VRAM in GB (e.g. 80)
  --max-vram          Maximum VRAM in GB
  --provider, -p      Provider filter (e.g. runpod, vastai, primeintellect, lambdalabs)
  --region            Region filter (e.g. US, EU)
  --resume, -r        Resume a previous session
  --volume, -v        Network volume name (RunPod, Lambda Labs)
  --image, -i         Docker image override (e.g. runpod/autoresearch:latest)
  --multi-gpu         Include multi-GPU instances
  --auto              Auto-select cheapest offer, no prompts

GPU Segments:
  consumer            RTX 3090, RTX 4090, RTX 5090
  workstation         RTX 2000/4000 Ada, A4000, A5000, RTX 6000 Ada, A6000
  datacenter          L4, A40, L40/L40S, A100, H100, H200, B200, B300

Default: --segment datacenter --min-vram 80

autofoundry config                                          Configure provider API keys
autofoundry inventory [-g GPU] [-s SEGMENT] [--min-vram N]  Browse GPU inventory
autofoundry volumes list                    List network volumes
autofoundry volumes create [--name] [--provider] [--size] [--region]
                                            Create a new network volume
autofoundry status [SESSION_ID]              Show operation status
autofoundry results [SESSION_ID]             Show experiment metrics
autofoundry teardown SESSION_ID              Terminate instances
```

## Architecture

```
cli.py           Entry point — run, config, inventory, volumes, status, results, teardown
gpu_filter.py    GPU tier definitions, name matching, and query resolution
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
