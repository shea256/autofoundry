# Autofoundry Documentation

Run any ML experiment script across GPUs on multiple cloud providers with a single command.

Autofoundry is a CLI companion to [Karpathy's autoresearch](https://github.com/karpathy/autoresearch). Point it at a shell script, pick your GPU configuration, and it handles the rest: provisioning instances, distributing experiment runs, streaming results live, and producing a final metrics report.

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [CLI Reference](#cli-reference)
- [Writing Experiment Scripts](#writing-experiment-scripts)
- [GPU Selection](#gpu-selection)
- [Network Volumes](#network-volumes)
- [Session Management](#session-management)
- [Custom Images](#custom-images)
- [Providers](#providers)
- [Architecture](#architecture)
- [Data Models](#data-models)
- [Session Persistence](#session-persistence)

---

## Installation

```bash
git clone https://github.com/autofoundry/autofoundry.git
cd autofoundry
uv tool install autofoundry
```

### Requirements

- Python 3.11+
- SSH key pair (ed25519 or RSA)
- At least one provider API key

### Supported Providers

| Provider | Type | Volumes | Multi-GPU |
|----------|------|---------|-----------|
| [RunPod](https://www.runpod.io/) | Secure and Community cloud | Yes | Yes |
| [Vast.ai](https://vast.ai/) | Global GPU marketplace | No | Yes |
| [PRIME Intellect](https://www.primeintellect.ai/) | Decentralized GPU network | No | Yes |
| [Lambda Labs](https://lambdalabs.com/) | On-demand cloud GPUs (bare metal) | Yes | Yes |

---

## Configuration

Run `autofoundry config` to interactively set up API keys, SSH key path, bandwidth filter, and HuggingFace token. Config is saved to `~/.config/autofoundry/config.toml`.

### Config File Format

```toml
ssh_key_path = "~/.ssh/id_rsa"
default_gpu_type = "H100"
default_segment = "datacenter"
default_min_vram = 80.0
min_bandwidth_mbps = 5000.0
huggingface_token = ""
last_script = ""
next_operation = 1

[api_keys]
runpod = "your_key_here"
vastai = "your_key_here"
primeintellect = "your_key_here"
lambdalabs = "your_key_here"
```

### Config Fields

| Field | Default | Description |
|-------|---------|-------------|
| `ssh_key_path` | `~/.ssh/id_rsa` | Path to SSH private key |
| `default_segment` | `datacenter` | GPU segment category |
| `default_min_vram` | `80.0` | Minimum VRAM in GB |
| `default_gpu_type` | `H100` | Legacy GPU type (backward compat) |
| `min_bandwidth_mbps` | `5000.0` | Min download speed filter for Vast.ai hosts |
| `huggingface_token` | `""` | HuggingFace token (forwarded as `HF_TOKEN` to instances) |
| `last_script` | `""` | Last script run (for quick re-run) |

### Environment Variable Fallbacks

Config values can also be set via environment variables. Precedence: `config.toml` > env vars / `.env` > defaults.

| Env Var | Config Field |
|---------|-------------|
| `RUNPOD_API_KEY` | `api_keys.runpod` |
| `VASTAI_API_KEY` | `api_keys.vastai` |
| `PRIMEINTELLECT_API_KEY` | `api_keys.primeintellect` |
| `LAMBDALABS_API_KEY` | `api_keys.lambdalabs` |
| `AUTOFOUNDRY_SSH_KEY_PATH` | `ssh_key_path` |
| `AUTOFOUNDRY_GPU_TYPE` | `default_gpu_type` |
| `AUTOFOUNDRY_MIN_BANDWIDTH_MBPS` | `min_bandwidth_mbps` |
| `HUGGINGFACE_TOKEN` | `huggingface_token` |

A `.env` file in the working directory is loaded automatically via `python-dotenv` on CLI startup.

### Migration

Old `default_tier` config values (e.g., `datacenter-80gb+`) are automatically migrated to `default_segment` + `default_min_vram` on load.

---

## CLI Reference

### `autofoundry run [SCRIPT]`

The main command. Provisions GPU instances, uploads and executes your script, streams output, and reports metrics.

```
Arguments:
  SCRIPT                Path to experiment shell script (prompted if omitted)

Options:
  --num, -n INTEGER     Number of experiment runs (default: 1)
  --gpu, -g TEXT        Specific GPU type (e.g. H100, "RTX 4090")
  --segment, -s TEXT    GPU segment: consumer, workstation, datacenter
  --min-vram FLOAT      Minimum VRAM in GB (e.g. 80)
  --max-vram FLOAT      Maximum VRAM in GB
  --provider, -p TEXT   Provider filter (runpod, vastai, primeintellect, lambdalabs)
  --region TEXT         Region filter (e.g. US, EU, secure, community)
  --volume, -v TEXT     Network volume name (creates if needed)
  --image, -i TEXT      Docker image override
  --multi-gpu           Include multi-GPU instances (default: single-GPU only)
  --auto                Auto-select cheapest offer, skip interactive prompts
  --resume, -r TEXT     Resume a previous session by ID
```

**Examples:**

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

# Attach a network volume (RunPod, Lambda Labs)
autofoundry run train.sh --volume my-data --provider runpod

# Resume a previous session
autofoundry run --resume <session-id>
```

### `autofoundry inventory`

Browse available GPU offers across all configured providers.

```
Options:
  --gpu, -g TEXT        GPU type filter (e.g. H100)
  --segment, -s TEXT    GPU segment (consumer, workstation, datacenter)
  --min-vram FLOAT      Minimum VRAM in GB
  --max-vram FLOAT      Maximum VRAM in GB
  --multi-gpu           Include multi-GPU instances
```

Shows up to 10 offers per provider initially; type a provider name to expand and see all. Offers are sorted by price ascending.

If no filters are provided, an interactive tier selection prompt is displayed.

### `autofoundry config`

Interactive setup for provider API keys, SSH key path, minimum bandwidth, and HuggingFace token. At least one provider API key is required.

### `autofoundry status [SESSION_ID]`

Show status of operations and their instances. Without a session ID, shows all operations.

### `autofoundry results [SESSION_ID]`

View experiment metrics from a completed operation. Without a session ID, shows the most recent. Displays a summary table (best/mean/worst/count per metric) and per-experiment details.

### `autofoundry volumes list`

List all persistent volumes across all configured providers. Shows provider, name, size, region, and mount path.

### `autofoundry volumes create`

Create a new persistent network volume.

```
Options:
  --name, -n TEXT       Volume name
  --provider, -p TEXT   Provider (runpod, lambdalabs)
  --size, -s INTEGER    Size in GB (RunPod only)
  --region, -r TEXT     Region / data center ID
```

### `autofoundry teardown SESSION_ID`

Terminate all instances for an operation and clean up resources.

---

## Writing Experiment Scripts

Your script runs in `/workspace` on a GPU instance with CUDA available. Scripts should be self-contained bash scripts.

### Reporting Metrics

To report metrics back to Autofoundry, print a `---` delimiter followed by `key: value` lines at the end of your script:

```bash
#!/usr/bin/env bash
set -e

# ... your training code ...

echo "---"
echo "val_loss: 0.42"
echo "accuracy: 91.3"
echo "training_seconds: 300"
```

Autofoundry parses everything after the `---` delimiter as metrics. Each line should be `key: value` where the value is numeric. Trailing `%` signs are stripped automatically.

Metrics are aggregated across all experiment runs in the final report, showing best, mean, worst, and count for each metric.

### Environment Variables Available on Instances

| Variable | Description |
|----------|-------------|
| `HF_TOKEN` | HuggingFace token (from config) |
| `AUTOFOUNDRY_IMAGE` | Docker image name (when `--image` is specified) |
| `PYTHONUNBUFFERED` | Set to `1` for unbuffered output |

### Included Scripts

**`scripts/run_autoresearch.sh`** — Clones [autoresearch](https://github.com/karpathy/autoresearch), installs deps via `uv` into a venv, and runs the training pipeline.

Three setup paths based on environment:

1. **Resume** — existing venv with torch found at `/workspace/.autoresearch_venv` → skips all setup (seconds)
2. **Pre-built image** — `AUTOFOUNDRY_IMAGE` contains "autoresearch" → inherits system torch, installs lightweight deps only
3. **Fresh install** — creates isolated venv, installs everything including torch (~3-5 min)

The venv is stored persistently at `/workspace/.autoresearch_venv` and survives stop/start cycles for fast resume.

---

## GPU Selection

### Segments and Tiers

GPUs are organized into segments (categories) and tiers (segment + VRAM range). The default is `--segment datacenter --min-vram 80`.

| Tier | Segment | VRAM Range | GPUs |
|------|---------|------------|------|
| Consumer 16GB+ | consumer | 16 GB+ | RTX 3090, RTX 4090, RTX 5090 |
| Workstation 16GB+ | workstation | 16–48 GB | RTX 2000 Ada, RTX 4000 Ada, RTX A4000, RTX A4500, RTX A5000, RTX Pro 4500 |
| Workstation 48GB+ | workstation | 48 GB+ | RTX 6000 Ada, RTX A6000, RTX PRO 6000 |
| Datacenter 24GB+ | datacenter | 24–40 GB | L4 |
| Datacenter 40GB+ | datacenter | 40–80 GB | A40, L40, L40S, A100 40GB |
| Datacenter 80GB+ | datacenter | 80–140 GB | A100 80GB, H100 |
| Datacenter 140GB+ | datacenter | 140 GB+ | H200, GH200, B200, B300 |

### GPU Name Matching

GPU name matching is case-insensitive and uses token prefix matching:

- **Single token** (e.g., `H100`): matches any GPU whose name contains a token starting with "H100" — matches "H100", "H100 SXM", "H100 NVL" but not "GH100"
- **Multi-token** (e.g., `RTX 4090`): matches GPUs where consecutive tokens each start with the query tokens — matches "RTX 4090", "NVIDIA RTX 4090" but not "RTX 4080"

### Selection Modes

- **Interactive** (default): Displays available offers grouped by provider. Select by number, type a provider name to expand hidden offers, or use `+` to add more instance types.
- **Auto** (`--auto`): Automatically selects the cheapest matching offer with no prompts.
- **Direct GPU** (`--gpu H100`): Filters to a specific GPU type across all providers.
- **Tier-based** (`--segment datacenter --min-vram 80`): Filters by GPU category and VRAM range.

### Multi-GPU Instances

By default, only single-GPU instances are shown. Use `--multi-gpu` to include multi-GPU offers.

When requesting multiple experiment runs (`--num 4`), Autofoundry pre-fetches distinct offers from the same provider to avoid contention — each instance gets its own offer if available.

---

## Network Volumes

Attach persistent storage so dependencies and data survive across runs. Supported on RunPod and Lambda Labs.

```bash
# First run — creates volume, installs deps to /workspace
autofoundry run train.sh --volume my-workspace --provider runpod

# Second run — finds existing volume, skips install
autofoundry run train.sh --volume my-workspace --provider runpod
```

| Provider | Mount Path | Notes |
|----------|-----------|-------|
| RunPod | `/workspace` | Created via REST API; attached via `networkVolumeId` |
| Lambda Labs | `/lambda/nfs/persistent-storage` | Persistent filesystem; attached via `file_system_names` |

### Managing Volumes

```bash
# List all volumes across providers
autofoundry volumes list

# Create a new volume
autofoundry volumes create --name my-data --provider runpod --size 100
autofoundry volumes create --name my-data --provider lambdalabs --region us-east-1
```

---

## Session Management

Every `autofoundry run` creates a session that tracks the full lifecycle of your experiment.

### Session Lifecycle

```
CONFIGURING → PLANNING → PROVISIONING → RUNNING → REPORTING → COMPLETED
                                                              → FAILED
                                                              → PAUSED
```

### Resuming Sessions

If a session is interrupted or paused, resume it to restart stopped instances and run remaining experiments:

```bash
autofoundry run --resume <session-id>
```

On resume:
- Stopped instances are restarted
- Instances already running are reused as-is
- Lost instances (deleted, errored, unreachable) are reported
- Pending experiments are executed
- The script detects existing venvs and skips setup

### Instance Lifecycle

After experiments complete, Autofoundry prompts you to:
- **Stop** instances — keeps disk, releases GPU. Enables fast restart via `--resume`.
- **Terminate** instances — fully deletes instance and disk.
- **Keep** instances — leaves them running (you pay for idle time).

A cleanup handler is registered for SIGINT/SIGTERM, so Ctrl+C also prompts for cleanup.

### Monitoring

```bash
# Show all sessions
autofoundry status

# Show a specific session with instance details
autofoundry status <session-id>

# View experiment metrics
autofoundry results
autofoundry results <session-id>
```

---

## Custom Images

Override the default provider image with `--image`:

```bash
autofoundry run train.sh --image runpod/autoresearch:1.0.2-cuda1281-ubuntu2204
```

Or declare per-provider images in your script header (first 20 lines):

```bash
#!/usr/bin/env bash
# autofoundry:image:runpod=runpod/autoresearch:1.0.2-cuda1281-ubuntu2204
# autofoundry:image:vastai=shea256/autoresearch:latest
```

### Image Precedence

1. CLI `--image` flag (highest priority — overrides everything)
2. Script `# autofoundry:image:<provider>=<image>` directives
3. Provider defaults (lowest priority)

### Default Provider Images

| Provider | Default Image |
|----------|--------------|
| RunPod | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` |
| Vast.ai | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` |
| PRIME Intellect | `cuda_12_4_pytorch_2_4` |
| Lambda Labs | None (bare metal, pre-configured Ubuntu) |

When `--image` is specified, the `AUTOFOUNDRY_IMAGE` environment variable is set on the remote instance so scripts can branch on which image is running.

---

## Providers

### RunPod

- **API**: REST at `https://rest.runpod.io/v1`, GraphQL at `https://api.runpod.io/graphql`
- **Instance type**: Docker containers on GPU nodes
- **SSH**: Container port 22 maps to a random host port (read from port mappings)
- **SSH key registration**: Via GraphQL `updateUserSettings` mutation
- **Volumes**: Network volumes via REST API, mount at `/workspace`
- **Regions**: Supports `secure` and `community` cloud types as region filters
- **Pod creation**: Returns HTTP 201 on success; `ports` must be an array (`["22/tcp"]`)

### Vast.ai

- **API**: REST at `https://console.vast.ai/api/v0`
- **Instance type**: Docker containers on marketplace hosts
- **SSH**: Uses `ssh_host` and `ssh_port` fields from instance details
- **SSH key registration**: POST to `/ssh/` endpoint
- **GPU filtering**: Client-side substring matching (server doesn't support exact GPU name filtering)
- **Bandwidth filtering**: Server-side via `inet_down` field (default 5000 Mbps, configurable)
- **VRAM filtering**: Server-side via `gpu_ram` field in MB (prevents result limit truncation)
- **Response format**: Offers are under the `"bundles"` key

### PRIME Intellect

- **API**: REST at `https://api.primeintellect.ai/api/v1` (camelCase responses)
- **Instance type**: Pods on decentralized GPU providers
- **SSH key setup**: Must set key as primary (`isPrimary: true`) — only the primary key is propagated to sub-providers
- **Blocked sub-provider**: `massedcompute` is filtered out (unreliable SSH and provisioning)
- **HTTP quirk**: Requires `follow_redirects=True` (API returns 307 for paths without trailing slashes)
- **Stock status**: "Low" counts as available

### Lambda Labs

- **API**: REST at `https://cloud.lambdalabs.com/api/v1` (basic auth)
- **Instance type**: Bare metal VMs (no Docker)
- **SSH key registration**: POST to `/ssh-keys`; retries with hash-based name on conflict
- **Volumes**: Persistent filesystems via `/file-systems`, mount at `/lambda/nfs/persistent-storage`
- **Region handling**: Each region appears as a separate offer with region metadata

---

## Architecture

```
cli.py           Entry point — run, config, inventory, volumes, status, results, teardown
gpu_filter.py    GPU tier definitions, name matching, and query resolution
planner.py       GPU offer querying, interactive/auto selection, multi-GPU support
provisioner.py   Instance lifecycle — provision, restart, stop, teardown, SSH key registration
executor.py      SSH-based script upload, execution, output streaming, metrics parsing
reporter.py      Metrics aggregation and display (best/mean/worst/count)
providers/       Provider API implementations (RunPod, Vast.ai, PRIME Intellect, Lambda Labs)
models.py        Data models (GpuOffer, InstanceConfig, VolumeInfo, Session, etc.)
config.py        TOML configuration management with env var fallbacks
state.py         SQLite session persistence (WAL mode)
theme.py         NGE-inspired terminal aesthetic
```

### Execution Flow

1. **CLI** parses arguments and loads config
2. **Planner** queries all configured providers concurrently (ThreadPoolExecutor, 4 workers), filters and ranks offers, and presents them for selection
3. **Provisioner** creates instances in parallel, registers SSH keys, and waits for SSH readiness (up to 15 minutes with exponential backoff)
4. **Executor** uploads the script via SCP, runs it via SSH with `-tt` for PTY and line-buffered streaming, and parses metrics from the output
5. **Reporter** aggregates metrics across all runs and displays the final report
6. **Cleanup** prompts to stop, terminate, or keep instances

### SSH Execution Details

- Uses subprocess SSH/SCP (not asyncssh)
- `BatchMode=yes` + `PasswordAuthentication=no` prevent password prompt hangs
- `-tt` flag forces PTY for line-buffered remote output streaming
- SSH retry loop: 30 attempts, 10s delay before upload (key auth can lag behind port availability)
- `PYTHONUNBUFFERED=1` is set for unbuffered Python output
- Script is uploaded to `/tmp/run_experiment.sh` and executed with `stdbuf -oL`

### Provisioning Details

- Offer retry loop: up to 5 attempts if an offer is taken
- Retryable errors: "no_such_ask", "not found", "unavailable", "already rented", "insufficient capacity", "out of stock", "503"
- SSH readiness polling: 900s timeout, exponential backoff (5s → 30s max), heartbeat every ~6 polls
- Multi-instance: threads maintain a shared set of claimed offer IDs to prevent retry storms

### Experiment Distribution

- Round-robin assignment: experiment `i` runs on instance `i % N`
- Sequential per instance (no GPU contention), parallel across instances
- Each experiment gets its own ExperimentResult with exit code, output, and metrics

---

## Data Models

### Core Types

| Model | Key Fields |
|-------|-----------|
| `GpuOffer` | provider, offer_id, gpu_type, gpu_count, gpu_ram_gb, price_per_hour, region, inet_down_mbps, availability, metadata |
| `InstanceConfig` | name, gpu_type, gpu_count (1), image, disk_gb (50), ssh_public_key, offer_id, volume_id, volume_region, metadata |
| `SshConnectionInfo` | host, port (22), username ("root"), key_path |
| `InstanceInfo` | provider, instance_id, name, status, gpu_type, gpu_count (1), price_per_hour, ssh, created_at |
| `VolumeInfo` | provider, volume_id, name, size_gb, region, mount_path |
| `ExperimentResult` | experiment_id, instance_id, run_index, status, metrics, raw_output, started_at, completed_at, exit_code |
| `ProvisioningPlan` | offers (list of (GpuOffer, count) tuples), total_experiments, script_path |
| `Session` | session_id, status, script_path, total_experiments, gpu_type, created_at, instances, results |

### Status Enums

**Session status:** `CONFIGURING` → `PLANNING` → `PROVISIONING` → `RUNNING` → `REPORTING` → `COMPLETED` / `FAILED` / `PAUSED`

**Instance status:** `PENDING`, `STARTING`, `RUNNING`, `STOPPING`, `STOPPED`, `ERROR`, `DELETED`

**Experiment status:** `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`

**Provider names:** `runpod`, `vastai`, `primeintellect`, `lambdalabs`

---

## Session Persistence

Sessions are stored as SQLite databases at `~/.config/autofoundry/sessions/{session_id}.db` using WAL mode for concurrent access.

### Database Schema

**Tables:**

- **`session`** — session_id, status, script_path, total_experiments, gpu_type, created_at
- **`instances`** — instance_id, provider, provider_instance_id, name, status, gpu_type, gpu_count, price_per_hour, ssh_host, ssh_port, ssh_username, created_at
- **`experiments`** — experiment_id (autoincrement), instance_id, run_index, status, started_at, completed_at, exit_code, raw_output
- **`results`** — experiment_id, key, value (composite primary key for metric key-value pairs)
- **`events`** — event_id (autoincrement), timestamp, event_type, data (JSON)

---

## Terminal Theme

Autofoundry uses an NGE-inspired terminal aesthetic. Key terminology mappings:

| Standard Term | Autofoundry Term |
|--------------|-----------------|
| Instance | UNIT |
| Experiment | SYNC TEST |
| Provisioning | ACTIVATION TEST |
| Results | INSTRUMENTALITY REPORT |
| Session | OPERATION |
| Provider | SUPPLY LINE |
| Planning | INVENTORY ASSESSMENT |
| Shutdown | TERMINATION PROTOCOL |
| Offers | RESERVES |

Instance and session statuses are also themed (e.g., "running" displays as "DEPLOYED", "stopped" as "STANDBY").
