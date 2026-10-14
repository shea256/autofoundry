---
name: autofoundry
description: Discover GPU offers, plan and run ML experiment scripts, collect results, and clean up cloud compute through Autofoundry's Python API. Use for RunPod, Vast.ai, PRIME Intellect, Lambda Labs, or Modal experiment workflows without interactive CLI automation.
license: MIT
---

# Autofoundry

Use the `autofoundry.api` Python library directly. Do not drive the terminal UI, parse
Rich tables, simulate prompts, or substitute a shell around the Autofoundry CLI.
This skill needs the matching Autofoundry package; read [the API reference](references/api.md)
for installation, capabilities, method signatures and runnable examples.

## Workflow

1. Establish the script, GPU family, **per-GPU** VRAM, GPU count, region, experiment
   count, time/cost constraints, result location and cleanup intent from the request.
   Preserve explicit constraints. If credentials are absent, still complete public
   Modal discovery and local planning; explain which authenticated work remains blocked.
2. Call `Autofoundry.discover` with an explicit provider list when scope is constrained.
   Return provider errors independently. A catalog row is not verified capacity;
   inspect `availability`, `execution_kind`, and `price_basis` before recommending it.
3. Produce a concrete local plan and explain cost assumptions and exclusions. Modal's
   `estimate()` includes compute components but leaves total cost unknown. Do not
   claim a script timeout is a spending cap or that host pricing includes all storage.
4. Submit only operations within the user's existing authorization. Discovery or a
   request for a plan does not authorize paid compute, key registration, account-resource
   creation, or remote execution. If authorization is missing, show the completed plan
   and ask before the mutation. Do not request confirmation again for an already
   authorized action within its agreed limits.
5. Run through the appropriate lifecycle below, inspect structured results, and report
   experiment outcomes separately from cleanup outcomes. Never retry an ambiguous
   creation or failed experiment automatically; first reconcile possible resources
   and side effects against the authorized scope.

## Choose the execution lifecycle

- **Modal**: use `plan_modal`, `run_modal`, and `cleanup_modal`. These are bounded
  serverless jobs under an existing App, with optional existing Volume storage.
  Keep exact A100 memory variants, `H100!`, GPU count and region; do not introduce
  fallback lists or upgrades for comparisons. `job.json` tracks the remote ID,
  observed hardware, metrics and cleanup. Retry cleanup only for that recorded job.
- **Host providers**: use `plan_host`, `create_host`, `get_host`/`wait_host`,
  `run_host_script`, and `terminate_host`. Save the plan before creation and the exact
  returned provider/instance ID immediately afterwards. Use a `finally` block for the
  agreed cleanup. A script/readiness timeout does not stop host billing; after a crash,
  recover the saved ID and inspect/terminate that resource. Respect a user's instruction
  to retain a host or volume. Do not perform workspace-wide cleanup.

Credentials stay in a secret-manager environment or official Modal configuration.
Never ask the user to paste keys into chat, store them in plans, or pass them through
command arguments. Host SSH uses a local key path and verified known-host entries;
do not disable verification to make a failed connection succeed. No local environment
or workload secrets are implicitly forwarded by the agent API.

The API is a local Python interface, not a hosted HTTP service or an installed MCP tool.
Installing this skill alone does not install its Python dependency or authorize spending.
