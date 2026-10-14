# Python API reference

Use Python 3.11+ and the Autofoundry revision distributed with this skill. In a checkout,
`uv sync --extra modal` installs the library and optional official Modal SDK. Outside a
checkout, install the matching reviewed Git commit using:

```bash
uv pip install 'autofoundry[modal] @ git+https://github.com/shea256/autofoundry.git@COMMIT_SHA'
```

Replace `COMMIT_SHA` with the exact commit from which this skill was copied. A packaged
archive includes `references/revision.md` with the exact matching install command. Do not
assume PyPI's `autofoundry` currently contains this API. The package source is MIT-licensed.
If you need only host providers, omit `[modal]`. The skill does not require the CLI.

## Discovery and local planning

```python
from autofoundry.api import Autofoundry, GpuQuery, ProviderName

client = Autofoundry()  # Public Modal planning does not read host credentials.
query = GpuQuery(gpu_type="A100", vram_min=80, single_gpu=True)
inventory = client.discover(query, providers=[ProviderName.MODAL])
data = inventory.model_dump(mode="json")  # provider results/errors; no credentials
spec = client.plan_modal(
    query, script="train.sh", gpu_count=1, app_name="existing-app",
    cpu=2, memory_mib=16384, timeout_seconds=300, region="us",
    artifacts=["/workspace/results.json"],
)
plan = {"request": spec.model_dump(), "selector": spec.selector, "estimate": spec.estimate()}
```

Use `Autofoundry.from_env()` for authenticated host discovery. Discovery defaults to
credentialed host providers plus Modal. An empty provider list
queries none. Host discovery makes read-only authenticated requests. Modal discovery
and planning need neither SDK installation nor credentials and read a dated public
catalog snapshot. `availability=None` means unknown, not zero or guaranteed capacity.

`GpuQuery` accepts `gpu_type`, `vram_min` (inclusive), `vram_max` (exclusive),
`single_gpu`, and `gpu_patterns`. For segment selection, use
`autofoundry.gpu_filter.resolve_query(segment="datacenter", vram_min=80)` to populate
patterns. When combining an explicit GPU and VRAM, construct `GpuQuery` directly so
both constraints are retained. Set `single_gpu=False` to discover multi-GPU rows and choose the required count;
`plan_modal` takes an explicit `gpu_count`. The API returns offers; it does not
auto-launch a winner.

`Autofoundry.from_env()` reads `RUNPOD_API_KEY`, `VASTAI_API_KEY`,
`PRIMEINTELLECT_API_KEY`, and `LAMBDALABS_API_KEY` from the process environment.
It does not load `.env` or the CLI config. Alternatively construct
`Autofoundry({ProviderName.RUNPOD: secret_value})` inside Python from a secret manager;
never put the literal value in a script or printed output. Do not pass Modal tokens
here: the official SDK owns `.modal.toml`, profiles and `MODAL_TOKEN_ID` plus
`MODAL_TOKEN_SECRET` configuration.

## Modal execution (only after authorization)

```python
import asyncio
from pathlib import Path

# In an async agent tool, await directly instead of calling asyncio.run().
record = asyncio.run(client.run_modal(spec, Path("results/job-001")))
# Inspect record['status'], ['exit_code'], ['metrics'], ['hardware'], ['cleanup'].
# If cleanup is unconfirmed, retry only this record:
# asyncio.run(client.cleanup_modal(Path("results/job-001")))
```

The directory must not exist. `run_modal` uses an existing App and, if specified,
an existing `volume` mounted at `/workspace`. It never creates/deletes Apps or Volumes.
Output is saved to `output.log`; repeated absolute `artifacts` paths under `/workspace`
are downloaded to `artifacts/` before termination. `job.json` persists state.

A failed experiment normally returns a failed record; cancellation propagates after
attempting cleanup. Invalid local inputs or missing SDK can raise a safe exception.
`cleanup_modal` raises if termination cannot be confirmed. Do not equate a successful
experiment with successful cleanup. Keep the same Modal profile/environment for recovery.

The timeout includes Sandbox startup and result collection; it is a remote lifetime
bound, not a total billing cap. GPU Sandboxes can be preempted; no automatic experiment
retry is applied. Without a Volume, storage is ephemeral. With a Volume, storage outlives
compute and can remain billable; background/final commits do not guarantee all writes
survive an abrupt failure. Consult the matching repository's `docs/modal.md` for current
pricing sources and the live-validation gate before production execution.

## Host execution (only after authorization)

```python
import asyncio
from pathlib import Path
from uuid import uuid4
from autofoundry.api import run_host_script

client = Autofoundry.from_env()
# Select a reviewed host offer from client.discover(...).offers; never a Modal offer.
plan = client.plan_host(
    offer, name=f"af-{uuid4().hex}",
    ssh_public_key=Path("~/.ssh/id_ed25519.pub").expanduser().read_text(),
)
Path("host-plan.json").write_text(plan.model_dump_json(indent=2))
instance = client.create_host(plan)  # One request; may register the supplied public key.
try:
    Path("host-instance.json").write_text(instance.model_dump_json(indent=2))
    ready = client.wait_host(instance, timeout=300)
    result = asyncio.run(run_host_script(
        ready, Path("train.sh"), ssh_key_path=Path("~/.ssh/id_ed25519"),
        directory=Path("results/host-job-001"), timeout=300,
        workdir="/workspace", known_hosts=Path("~/.ssh/known_hosts"),
    ))
finally:
    # Apply this cleanup only when deletion is the user's agreed lifecycle.
    client.terminate_host(instance.provider, instance.instance_id)
```

Host-key entries must be verified through a trusted provider channel before connection.
`known_hosts=None` uses the user's standard known_hosts file; verification is never
disabled. The API uses AsyncSSH and does not inherit SSH config environment forwarding.
The remote working directory must already exist (bare-metal hosts may need a different
path). `plan_host` accepts explicit `image`, `disk_gb`, `volume_id`, `volume_region`;
provider image semantics remain native (e.g. Lambda is bare metal).

A create failure raises `ApiError(code="creation_unconfirmed")`; the provider may have
allocated a resource even though no ID returned. Do not repeat the create automatically.
Reconcile the unique plan name in that provider. Host operations have no automatic
failover or resource-lifetime guarantee. `terminate_host` requests deletion of exactly
one ID; use `get_host`/the provider dashboard to confirm release and billing state.
Persistent volumes are not deleted. No stop/start or volume-creation wrappers are exposed.

`run_host_script` writes partial `output.log` (4 MiB cap) and `result.json` with status,
exit code, error code and metrics parsed after `---`. It uploads only the script, forwards
no secrets and downloads no host artifact trees. It does not terminate the host. A
local timeout/disconnection cannot prove that every remote child process has exited.
Use the agreed exact-host teardown to bound continuing compute, and inspect cleanup
errors separately so they do not hide the original execution outcome.

## Error/result contract

- Pydantic results support `model_dump(mode="json")` / `model_dump_json()`.
- Provider inventory entries contain an `error` code independently of healthy providers.
- `ApiError.code` is safe to report; do not log internal exception contexts or credential objects.
- Modal job failures use safe messages in the job record; SDK response bodies are suppressed.
- Importing `autofoundry.api` does not import the terminal UI, authenticate, print or allocate.
