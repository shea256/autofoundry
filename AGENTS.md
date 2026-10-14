# Autofoundry

Python library and CLI for ML experiments across GPU providers.
Agent-facing usage is defined by `.agents/skills/autofoundry/SKILL.md`.
`autofoundry run <script>` → pick GPUs → provision → execute → stream output → report metrics → teardown.

## Working in this repository

- Keep reusable behavior in the Python library. `autofoundry.api` must not import the
  CLI, prompt, print terminal UI, load `.env`, or write user configuration.
- Keep provider-specific details in adapters; host and serverless lifecycles differ.
- Never include credentials in source, logs, error payloads, command arguments or chat.
- Run `uv run --extra modal python -m pytest -q`, Ruff on changed files, and `git diff --check`.
  Full-repository Ruff currently has 35 baseline findings; do not introduce more.
- Test provider changes with mocks. Do not use real credentials, create account resources
  or launch paid workloads unless the user's authorization explicitly includes that work.
- For skill changes, validate `.agents/skills/autofoundry/SKILL.md` and run the API tests.
  Keep the skill portable: references resolve within its own folder, not a developer's home.
- `AGENTS.md` is the canonical repository guidance. Do not maintain duplicate `.claude`
  instruction files. Shared skills live under `.agents/skills/`.

## Architecture

```
api.py → providers + metrics (non-interactive library)
cli.py → planner.py → provisioner.py → executor.py → reporter.py (terminal UX)
```

- **Agent API**: `src/autofoundry/api.py` — structured discovery, local plans, explicit host lifecycle, SSH scripts, Modal jobs and cleanup
- **Shared logic**: `metrics.py` and `defaults.py` — UI-free parsing and image defaults
- **CLI**: `src/autofoundry/cli.py` — `run`, `config`, `inventory`, `volumes` (list, create), `status`, `results`, `teardown` commands via Typer
- **Models**: `src/autofoundry/models.py` — GpuOffer, InstanceConfig, InstanceInfo, VolumeInfo, ProvisioningPlan
- **Config**: `src/autofoundry/config.py` — TOML config at `~/.config/autofoundry/config.toml` (custom serializer outputs lowercase `true`/`false` for booleans); includes `min_bandwidth_mbps` (default 5000), `default_segment` (default `datacenter`), `default_min_vram` (default `80`), and `huggingface_token`; all values support env var fallbacks (config.toml takes precedence)
- **GPU Filter**: `src/autofoundry/gpu_filter.py` — GPU tier definitions (category+VRAM), name matching, VRAM filtering, and query resolution
- **Providers**: `src/autofoundry/providers/{runpod,vastai,primeintellect,lambdalabs,modal}.py`
- **Theme**: `src/autofoundry/theme.py` — NGE-inspired terminal aesthetic ("operations", "units", "supply lines", "reserves", "sync test"); `term()` helper selects singular/plural forms based on count
- **State**: `src/autofoundry/state.py` — SQLite-backed session persistence (WAL mode)

## Run Modes
1. **Scratch** — self-contained script installs everything from zero (e.g. `run_autoresearch.sh`). Simplest, always works.
2. **Network volumes** — `--volume my-vol` attaches persistent storage. First run installs deps to volume, subsequent runs skip setup.
3. **Start/stop** — keep instances alive between experiments via stop/resume. Fastest iteration.

## Provider API Details

### RunPod
- REST API at `https://rest.runpod.io/v1`, GraphQL at `https://api.runpod.io/graphql`
- REST uses `Authorization: Bearer` + `x-api-key` headers
- GraphQL MUST use `Authorization: Bearer` header (not `api_key` header) for user-scoped queries like `myself`
- Pod creation returns 201 (not 200) — check `status_code >= 300` for errors
- **SSH port mapping**: Container port 22 maps to a random host port. Read `pod["portMappings"]["22"]` for actual port. Do NOT hardcode port 22.
- **SSH key auth**: Keys must be registered in RunPod account settings via `updateUserSettings` GraphQL mutation. Env vars (`SSH_PUBLIC_KEY`, `PUBLIC_KEY`) alone are NOT sufficient.
- `ports` field in pod creation must be an array: `["22/tcp"]` not `"22/tcp"`
- GraphQL `gpuTypes` query does NOT support `maxGpuCount` field
- Provider image: `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`
- **Network volumes**: REST `POST /networkvolumes` to create, GraphQL `myself { networkVolumes }` to list
- Attach via `networkVolumeId` in pod creation payload, mounts at `/workspace`

### Vast.ai
- Response uses `"bundles"` key (not `"offers"`)
- Auth: `Authorization: Bearer` header on httpx client for most endpoints
- `create_instance` PUT passes `api_key` as query param (not header)
- GPU name filtering must be client-side (substring match via `_find_gpu_variants`), not exact match
- **Bandwidth filtering**: `inet_down` field in query filters by min download speed (default 5000 Mbps, configurable via `min_bandwidth_mbps` in config)
- **VRAM filtering**: `gpu_ram` field in query supports server-side VRAM min filtering (in MB) for tier-based queries, avoiding result limit (100) returning only cheap small GPUs
- **SSH connectivity**: Use `ssh_host` and `ssh_port` fields from instance details (not `public_ipaddr`)
- SSH key registration: POST to `/ssh/` (not PUT), no `api_key` query param needed (uses Bearer header)
- Provider image: `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`

### PRIME Intellect
- API returns camelCase fields: `gpuType`, `gpuMemory`, `cloudId`, `prices.onDemand`
- httpx client requires `follow_redirects=True` (API returns 307 for paths without trailing slashes)
- SSH key endpoints require trailing slashes: `/ssh_keys/`, `/ssh_keys/{id}/`
- SSH key must be set as primary (`isPrimary: true` via PATCH) — PI only propagates primary key to sub-providers
- `massedcompute` sub-provider is filtered out (unreliable SSH key propagation and provisioning)
- `create_instance` requires nested `{"pod": {...}, "provider": {...}}` payload
- `stockStatus` values: "Low" counts as available; only exclude "", "out_of_stock", "unavailable"
- Null safety: use `str(item.get("field") or "")` for metadata dict values (Pydantic rejects None in `dict[str, str]`)
- Provider image: `cuda_12_4_pytorch_2_4`

### Lambda Labs
- API: `https://cloud.lambdalabs.com/api/v1`, basic auth (API key as username)
- `_ensure_ssh_key()` — register SSH key, retries with hash-based name on conflict
- Bare metal VMs, no Docker image field — uses provider's pre-configured Ubuntu image
- **Persistent filesystems**: `POST /file-systems` to create, `GET /file-systems` to list
- Attach via `file_system_names` in launch payload, mounts at `/lambda/nfs/persistent-storage`
- Region handling: each region is separate offer with metadata

### Modal

- Serverless GPU Sandboxes, not SSH hosts. Use `ModalJobSpec` and `run_job`/`cleanup_job`.
- Public catalog capacity is unknown. Prices are a dated snapshot; compute estimates
  include Sandbox CPU/RAM and region multipliers, not total cost.
- Official SDK token/profile configuration only. No Autofoundry API-key field for Modal.
- Existing App and optional Volume lookup only; no implicit account-resource creation.
- Exact A100 memory variants and `H100!`; no fallback lists or automatic upgrades.
- Run once, persist job ID and results, attempt bounded exact-resource cleanup.
- See `docs/modal.md` for sources, semantics and remaining live-validation gate.

## Environment Forwarding
- `python-dotenv` loads `.env` on CLI startup (`cli.py`)
- Config precedence: config.toml > env vars/.env > defaults
- Env var fallbacks: `RUNPOD_API_KEY`, `VASTAI_API_KEY`, `PRIMEINTELLECT_API_KEY`, `LAMBDALABS_API_KEY`, `HUGGINGFACE_TOKEN`, `AUTOFOUNDRY_SSH_KEY_PATH`, `AUTOFOUNDRY_GPU_TYPE`, `AUTOFOUNDRY_MIN_BANDWIDTH_MBPS`
- `HUGGINGFACE_TOKEN` from config is forwarded to remote instances as `HF_TOKEN`
- `AUTOFOUNDRY_IMAGE` is forwarded when `--image` is specified, so scripts can branch on which image is running

## SSH Execution
- CLI `executor.py` uses subprocess SSH/SCP. Agent API uses AsyncSSH with verified host keys and no environment forwarding.
- `BatchMode=yes` + `PasswordAuthentication=no` prevent password prompt hangs
- CLI SSH retry loop (30 attempts, 10s delay) before upload — key auth can lag behind port availability
- Metadata passthrough: `GpuOffer.metadata` → `InstanceConfig.metadata` → provider's `create_instance`

## Session Persistence
- SQLite at `~/.config/autofoundry/sessions/{session_id}.db`
- Tables: session, instances, experiments, results, events
- Session states: CONFIGURING → PLANNING → PROVISIONING → RUNNING → REPORTING → COMPLETED/FAILED/PAUSED
- Resume support: `--resume` flag restarts stopped instances and runs pending experiments

## GPU Tier System
- Tiers combine a **segment** (consumer, workstation, datacenter) with a **VRAM range** and **GPU name patterns**
- 7 internal tiers used for pattern matching and interactive selection
- Default: `--segment datacenter --min-vram 80` (A100 80GB, H100)
- `gpu_name_matches()` supports multi-token patterns (e.g. "RTX 4090" matches "NVIDIA RTX 4090") via consecutive token prefix matching
- Patterns define the GPU family, VRAM range disambiguates variants (e.g. A100 appears in both 40GB and 80GB tiers)
- `tier_for_gpu(gpu_name, vram_gb)` classifies a GPU into a tier using both name patterns and VRAM range
- Old `default_tier` config values (e.g. `datacenter-80gb+`) are auto-migrated to `default_segment` + `default_min_vram` in `Config.load()`
- Both `run` and `inventory` commands use interactive tier selection; users can also type a GPU name directly at the prompt
- CLI flags: `--gpu` for specific GPU name, `--segment`/`-s` for category, `--min-vram`/`--max-vram` for VRAM range

## Inventory UI
- `planner.py` displays up to 10 GPU offers per provider initially, with interactive expansion to view all
- Provider status messages show post-filter counts (matching the displayed results)

## Scripts
- `scripts/run_autoresearch.sh` — clone, install deps via uv into a venv, run. Works from scratch or with volumes (pulls on re-run).
- Scripts can declare `# autofoundry:image:<provider>=<image>` in the header (first 20 lines) to override the default provider image
- CLI `--image` flag overrides all provider images (takes precedence over script directives and defaults)
- `run_autoresearch.sh` uses the default provider image (lightweight pytorch base); creates a venv and installs torch 2.9.1 + deps via uv at runtime
- Venv stored persistently at `/workspace/.autoresearch_venv` (survives stop/start cycles for fast resume)
- Three setup paths based on `AUTOFOUNDRY_IMAGE` env var:
  1. **Resume** — existing venv with torch found → skips all setup (seconds)
  2. **Pre-built image** — `AUTOFOUNDRY_IMAGE` contains "autoresearch" → inherits system torch, installs lightweight deps only
  3. **Fresh install** — isolated venv, installs everything including torch (~3-5 min)
- Venv approach avoids "externally managed" Python errors on Ubuntu 24.04+ images where system Python is PEP 668-protected
- Script outputs `---` delimiter followed by `key: value` metrics, parsed by `metrics.parse_metrics()` (re-exported by `executor` for compatibility).

