# Modal serverless execution

Autofoundry supports Modal through a separate `ServerlessProvider` interface. A Modal
job is a bounded GPU Sandbox, not a rented SSH host. Existing RunPod, Vast.ai, PRIME
Intellect and Lambda host orchestration is unchanged. Modal is visible in inventory,
but is deliberately excluded from automatic host recommendations and mixed host plans.
Use `run --provider modal` or the dedicated `modal` commands to opt into execution.

## Install and authenticate securely

```bash
uv tool install 'autofoundry[modal]'
# From a checkout instead:
uv sync --extra modal
```

The optional dependency is the official Modal Python SDK, version `>=1.6.1,<2`
(the lockfile and local API-contract checks use 1.6.1). Catalog discovery and local
planning do not import the SDK, read tokens, authenticate or allocate anything.

Configure authentication using Modal's own CLI, in a private terminal:

```bash
modal token set --token-id - --token-secret -
```

The dashes request hidden stdin input; do not substitute token values into arguments.
Alternatively inject **both** `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` using your
secret manager's environment integration. The SDK handles `.modal.toml`, active
profiles, `MODAL_PROFILE`, and `MODAL_CONFIG_PATH`. Keep the config outside this
repository with owner-only permissions. Do not put Modal credentials in Autofoundry's
`[api_keys]`, scripts, committed `.env` files, command arguments, logs or chat.
Autofoundry neither stores nor forwards Modal tokens, and suppresses raw SDK exception
payloads. Keep SDK debug logging disabled. See [official token configuration](https://modal.com/docs/reference/modal.config).

```bash
# Explicit read-only authentication check; no App, Volume, or compute creation:
autofoundry modal auth-check
```

Execution requires an **existing Modal App** (default name `autofoundry`, override
with `--app`) in the selected workspace/environment. Optional `--volume` also refers
to an existing named Volume. Autofoundry does not create either implicitly. Prepare
these separately through Modal when authorized; [App.lookup](https://modal.com/docs/reference/modal.App)
documents App lookup/creation. No account resources were created to validate this adapter.

## Discover and plan without credentials

```bash
autofoundry inventory --provider modal --gpu A100 --min-vram 80
autofoundry inventory --gpu H100  # configured host providers plus Modal catalog

autofoundry modal run train.sh --gpu A100 --min-vram 80 --gpu-count 2 \
  --region eu --cpu 4 --memory-mib 32768 --timeout 1800 --dry-run
```

Discovery is a **published catalog snapshot dated 2026-10-14**, not a live price or
capacity API. No documented free-capacity query was found. Availability is `unknown`
(`GpuOffer.availability = None`), including for regional and multi-GPU requests.
An accepted catalog request can still queue or fail due to capacity, quotas, payment
setup or image compatibility. Provider discovery failures are reported independently.
Refresh the constants and source verification date when official rates change.

Catalog inventory uses 2 physical CPU cores and 16 GiB RAM per Sandbox; its hourly
column is an **estimated compute rate**, not total cost. The dry-run breakdown uses
the actual requested GPU count, CPU and RAM. `total_cost` remains unknown. Pricing is
per second, RAM billing uses GiB, and SDK memory requests use MiB. Execution sets CPU
and RAM requests equal to their limits to avoid unpriced bursting. Limits can throttle
CPU or terminate a memory-hungry process. The estimate applies regional compute
multipliers and separately reports Volume and egress unit rates; allowances and credits
are not assumed. Additional usage, image builds, retained storage, account plan fees
and taxes prevent this from being an all-in quote or spending cap. GPU time includes
Sandbox setup and result collection. Review [pricing](https://modal.com/pricing) and
[Sandbox resource billing](https://modal.com/docs/guide/sandbox-resources).

`--region` accepts exact documented Modal codes, normalized to lowercase. Broad
`us`, `eu`, `ap` requests use 1.15×; narrower codes use 1.75× on GPU + CPU + RAM.
Unknown codes fail before authentication. The region is passed to `Sandbox.create`;
it is a placement constraint, not verified regional capacity or a promise that all
storage/control-plane data stays there. See [region selection](https://modal.com/docs/guide/region-selection).

## Hardware selection and comparisons

VRAM filters apply **per GPU**, never to aggregate memory. `A100 --min-vram 80`
selects `A100-80GB`; two 40 GB cards cannot satisfy that filter. GPU counts remain
part of the request and price. Family matching distinguishes L4 from L40S.

Autofoundry sends one strict selector: `A100-40GB`, `A100-80GB`, `H100!`, or another
explicit family, with `:N` for count. It never sends a GPU fallback list, ambiguous
`A100`, upgrade-enabled `H100`, or `B200+`. Modal's ordered fallback lists are a
Function feature; Sandbox requests accept one GPU selector. This adapter deliberately
disables fallback and upgrade policies for controlled comparisons. Before the script,
`nvidia-smi` must match the requested family, count and nominal memory (up to 10% below / 5% above
for decimal-GB versus MiB reporting and reserved memory). Observed hardware is saved separately from metrics;
a mismatch fails before experiment execution. This does not certify identical clocks,
CPU models, topology, performance or usable free VRAM. See [GPU selection policies](https://modal.com/docs/guide/gpu).

The snapshot includes T4, L4, A10, L40S, both A100 variants, RTX PRO 6000, H100,
H200, B200 and B300. B200 uses Modal's [180 GB specification](https://modal.com/blog/introducing-b200-h200).
RTX PRO 6000 is [96 GB](https://modal.com/blog/product-updates-rtx-pro-6000-command-k-sandbox-fs-api-and-more)
and is conservatively offered with one GPU because the GPU guide does not specify its
multi-GPU limit. Other count limits follow that guide.

## Execute and collect results

These commands allocate paid compute; run them only when ready to authorize that spend:

```bash
autofoundry modal run train.sh --app my-existing-app --gpu H100 \
  --cpu 4 --memory-mib 32768 --timeout 1800 \
  --volume my-existing-data --artifact /workspace/results.json

# Convenient alias: default App, 2 cores, 16 GiB RAM, 1 GPU, one-hour lifetime:
autofoundry run train.sh --provider modal --gpu A100 --min-vram 80 --num 2 --auto
```

`modal run --num N` runs N independent jobs sequentially, without retrying failed
experiments. Use `--gpu-count` for GPUs within one job. The alias accepts existing
`--gpu`, VRAM, segment, region, image, volume and experiment-count options. Use the
Modal command for CPU/RAM/lifetime/artifact settings. There is no SSH setup,
`instance up/stop/restart`, host `--resume`, or mixed-provider scheduling for Modal.

Only the specified shell script is uploaded, to `/tmp/autofoundry.sh`, and run with
Bash in `/workspace`. Install dependencies in the script or use `--image`; the default
is a CUDA 13.1 runtime image, not a preinstalled ML environment. Image override
precedence is CLI, `# autofoundry:image:modal=...`, then default. B300 requires compatible
CUDA 13.1+ libraries. Local directories, API keys and HuggingFace tokens are **not**
forwarded. Custom credential injection and private image registry authentication are
not implemented. Scripts should never print their own secrets.

Each job prints a local directory under `~/.config/autofoundry/modal-jobs/` (override
parent with `--output`). `job.json` contains the request, estimate, remote ID, observed
hardware, exit code, metrics, status and cleanup outcome. `output.log` captures combined
stdout/stderr, including partial output on failure; output is capped at 4 MiB. Numeric
metrics use the existing `---` delimiter format. Repeat `--artifact` for explicit files
under `/workspace`; files download to `artifacts/` before termination. No recursive
filesystem export occurs. Collection uses the documented [Sandbox filesystem API](https://modal.com/docs/guide/sandbox-files)
and its file-size limits. A failed download marks the job failed while retaining any
already collected output, metrics and exit code. Inspect these files directly; host
SQLite `status/results/teardown` commands do not manage Modal jobs.

## Persistence, interruption and cleanup

Without a Volume, the filesystem is ephemeral and disappears with the Sandbox. With
`--volume`, `/workspace` persists independently and continues incurring applicable
storage charges after compute ends. Modal documents periodic background Volume commits
and a final commit on Sandbox termination; applications needing stronger checkpoint
boundaries should use the documented v2 `sync` operation. Abrupt failure can lose recent
writes. Shared Volumes require application-level coordination. See [Volume syncing](https://modal.com/docs/guide/sandbox-files#using-volumes).

GPU Sandboxes can be preempted. Autofoundry makes one execution attempt and does not
promise exactly-once side effects or apply Function automatic retry semantics to
Sandboxes. Checkpoint and make scripts idempotent before explicitly submitting another
job. See [preemption](https://modal.com/docs/guide/preemption).

The remote Sandbox lifetime is capped by `--timeout` (1–86400 seconds), including
startup and collection; allow time for both. Client API operations are bounded, with
60 seconds for authentication/lookups/creation and 30 seconds for cleanup. Slow image
builds can exceed the create deadline and leave the result uncertain. The job name is
journaled before creation and the Sandbox ID immediately afterwards. SIGINT/SIGTERM
attempt cleanup; client crashes or lost responses rely on the remote lifetime cap.

Cleanup uses documented [`Sandbox.terminate(wait=True)`](https://modal.com/docs/reference/modal.Sandbox).
It only terminates this job's Sandbox, never enumerates the workspace, and never deletes
Apps, Volumes, images or snapshots. Cleanup failure is recorded separately from the
experiment result and stops further submissions in a batch. Retry with the same Modal
profile/workspace/environment:

```bash
autofoundry modal cleanup /path/to/printed/job-directory
```

Recovery uses the recorded ID, or the exact App + unique name after an ambiguous create
response, and checks the job ownership tag before terminating. Already confirmed
cleanup is a local no-op. Failure to resolve a resource is not falsely reported as
successful deletion: inspect the workspace and await the lifetime bound if necessary.

## Validation gate

Local mocked tests cover discovery, auth delegation/redaction, unit conversions,
regional constraints, hardware checks, uploads, execution, result collection, failures,
interruptions and scoped cleanup. No credentials were validated, remote workloads run,
paid resources launched or account resources created during development. Before relying
on production execution, an authorized operator must validate a small paid Sandbox with
their actual workspace, image, selected hardware/region, optional Volume, artifacts and
cleanup. Mock tests and SDK signature checks do not establish live capacity or billing.
