# Manual End-to-End Test Workflows

Run these in order. Each builds on the previous.

## 1. CLI basics

```bash
# Should show themed help with all commands
autofoundry

# Should show run options including --volume
autofoundry run --help

# Should NOT have a build command
autofoundry build --help  # expect error
```

**Pass:** Help shows config, reserves, volumes, run, status, results, teardown. No build command.

---

## 2. Config

```bash
# Should show existing config and let you skip already-configured providers
autofoundry config
```

**Pass:** Already-configured providers show "configured" and default to not reconfiguring.

---

## 3. Browse reserves

```bash
autofoundry reserves
autofoundry reserves --gpu A100
```

**Pass:** Shows GPU reserves from configured providers in a formatted table.

---

## 4. List volumes

```bash
autofoundry volumes
```

**Pass:** Shows existing volumes from RunPod and Lambda Labs (or "No volumes found" if none exist).

---

## 5. Scratch run — RunPod

```bash
autofoundry run scripts/run_autoresearch.sh --provider runpod --auto
```

Or walk through interactively and select a RunPod offer.

**Pass:** Instance provisions, script uploads, autoresearch clones + installs + runs, metrics reported, teardown prompt works.

---

## 5b. Scratch run — Lambda Labs

```bash
autofoundry run scripts/run_autoresearch.sh --provider lambdalabs --region US --auto
```

**Pass:** Bare metal VM provisions (no Docker), SSH key registered, script runs, metrics reported, teardown works.

---

## 5c. Scratch run — Vast.ai

```bash
autofoundry run scripts/run_autoresearch.sh --provider vastai --auto
```

**Pass:** Instance provisions via marketplace PUT, SSH connects using `ssh_host`/`ssh_port` fields, script runs, metrics reported, teardown works.

---

## 5d. Scratch run — PRIME Intellect

```bash
autofoundry run scripts/run_autoresearch.sh --provider primeintellect --auto
```

**Pass:** SSH key registered and set as primary, instance provisions (massedcompute sub-provider excluded), script runs, metrics reported, teardown works.

---

## 6. Start/stop/resume cycle

During the run from test 5 (or a new run), when prompted "What to do with units?":

```
Choose: stop
```

Then resume:

```bash
# Use the operation ID shown (e.g. op-55)
autofoundry run --resume op-55
```

**Pass:** Instance restarts, pending experiments run, results reported.

---

## 7. Status and results

```bash
# List all operations
autofoundry status

# Detail for a specific operation
autofoundry status op-55

# View experiment metrics
autofoundry results op-55
```

**Pass:** Shows session status, instance details, completed/pending counts, metrics table.

---

## 8. Teardown

```bash
autofoundry teardown op-55
```

**Pass:** Confirms before terminating, deletes instances, marks operation completed.

---

## 9. Volume run (RunPod)

Create a volume and run with it:

```bash
autofoundry run scripts/run_autoresearch.sh --volume af-workspace
```

Walk through the prompts:
- If volume doesn't exist: confirm creation (100GB, US-TX-3)
- Experiments: 1
- GPU type: H100
- Select a RunPod offer

**Pass:** Volume created (or found), attached to pod, script runs with `/workspace` persisted.

Verify volume exists:

```bash
autofoundry volumes
```

Run again with the same volume (should find it, not create):

```bash
autofoundry run scripts/run_autoresearch.sh --volume af-workspace
```

**Pass:** Second run finds existing volume, skips creation. If deps were installed to `/workspace` on first run, they persist.

---

## 10. Volume with incompatible provider

```bash
autofoundry run scripts/run_autoresearch.sh --volume my-vol
```

Select PRIME Intellect or Vast.ai instead of RunPod/Lambda Labs.

**Pass:** Shows error "Network volumes not supported on: primeintellect", continues without volume.

---

## 11. Quick provider scripts

Each provider has a build-and-run script for one-command end-to-end testing:

```bash
scripts/build_and_run_autoresearch_on_runpod.sh
scripts/build_and_run_autoresearch_on_lambdalabs.sh
scripts/build_and_run_autoresearch_on_vastai.sh
scripts/build_and_run_autoresearch_on_primeintellect.sh
```

**Pass:** Each script builds autofoundry from source and runs autoresearch on the target provider end-to-end.

---

## Cleanup

Delete any test volumes via the RunPod or Lambda Labs dashboard (no CLI delete command yet).
Teardown any remaining operations:

```bash
autofoundry status
autofoundry teardown <op-id>
```
