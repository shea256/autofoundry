# Autofoundry

CLI tool to run ML experiment scripts across GPUs on multiple cloud providers.
`autofoundry run <script>` → pick GPUs → provision → execute → stream output → report metrics → teardown.

## Architecture

```
cli.py → planner.py → provisioner.py → executor.py → reporter.py
```

- **CLI**: `src/autofoundry/cli.py` — `run`, `config`, `reserves`, `volumes`, `status`, `results`, `teardown` commands via Typer
- **Models**: `src/autofoundry/models.py` — GpuOffer, InstanceConfig, InstanceInfo, VolumeInfo, ProvisioningPlan
- **Config**: `src/autofoundry/config.py` — TOML config at `~/.config/autofoundry/config.toml`
- **Providers**: `src/autofoundry/providers/{runpod,vastai,primeintellect,lambdalabs}.py`
- **Theme**: `src/autofoundry/theme.py` — NGE-inspired terminal aesthetic ("operations", "units", "supply lines", "reserves", "sync tests")
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
- Uses `api_key` as query param
- GPU name filtering must be client-side (substring match via `_find_gpu_variants`), not exact match
- Provider image: `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`

### PRIME Intellect
- API returns camelCase fields: `gpuType`, `gpuMemory`, `cloudId`, `prices.onDemand`
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

## SSH Execution
- `executor.py` uses subprocess SSH/SCP (not asyncssh, despite the dependency)
- `BatchMode=yes` + `PasswordAuthentication=no` prevent password prompt hangs
- `-tt` flag forces PTY for line-buffered remote output streaming
- SSH retry loop (10 attempts, 5s delay) before upload — key auth can lag behind port availability
- Metadata passthrough: `GpuOffer.metadata` → `InstanceConfig.metadata` → provider's `create_instance`

## Session Persistence
- SQLite at `~/.config/autofoundry/sessions/{session_id}.db`
- Tables: session, instances, experiments, results, events
- Session states: CONFIGURING → PLANNING → PROVISIONING → RUNNING → REPORTING → COMPLETED/FAILED/PAUSED
- Resume support: `--resume` flag restarts stopped instances and runs pending experiments

## Scripts
- `scripts/run_autoresearch.sh` — clone, install deps, run. Works from scratch or with volumes (pulls on re-run).
- Script outputs `---` delimiter followed by `key: value` metrics, parsed by `executor.parse_metrics()`

## Status
- RunPod: fully working (provision, execute, stream, report, teardown, volumes) ✓
- Lambda Labs: fully working (provision, execute, stream, report, teardown) ✓
- Vast.ai: GPU listing works, provisioning untested
- PRIME Intellect: GPU listing works (inventory fluctuates), provisioning untested
