# Agent API and shareable skill

Autofoundry has a non-interactive Python API at `autofoundry.api`. Agents can discover
GPUs, construct local plans, explicitly provision hosts or execute Modal jobs, collect
results and clean up exact resources. No terminal UI, prompts, table scraping, CLI config
loading or implicit `.env` loading is required. This is a Python library interface,
not a hosted HTTP API or MCP server.

Repository development instructions live in root `AGENTS.md`. The portable agent skill
is `.agents/skills/autofoundry/SKILL.md`, with a self-contained API reference, optional
UI metadata and MIT license. Development guidance and end-user execution guidance are
separate: copying the skill does not copy repository maintenance instructions.

## Use the library

```python
from autofoundry.api import Autofoundry, GpuQuery, ProviderName

client = Autofoundry()  # Public catalog; no credential reads.
inventory = client.discover(
    GpuQuery(gpu_type="A100", vram_min=80),
    providers=[ProviderName.MODAL],
)
print(inventory.model_dump_json(indent=2))
spec = client.plan_modal(
    GpuQuery(gpu_type="A100", vram_min=80), script="train.sh",
    gpu_count=2, region="us", app_name="existing-app", timeout_seconds=300,
)
print(spec.model_dump_json(indent=2))
print(spec.estimate())
```

This example does not authenticate or create resources. Actual execution is a separate
explicit call: `await client.run_modal(spec, new_job_directory)`. Host workflows expose
`plan_host`, `create_host`, `get_host`, `wait_host`, `run_host_script`, and
`terminate_host`. See the [skill API reference](../.agents/skills/autofoundry/references/api.md)
for complete examples and lifecycle/error contracts.

Host API keys come from explicit Python arguments or existing process environment
variables, never from CLI prompts. Modal authentication uses its official configuration.
The API does not forward local credentials to workloads. Host SSH verifies known-host
keys and returns structured results. Host resources continue billing until released;
script timeouts do not act as host lifetime or spending limits. The current API provides
host stdout/metrics; explicit file artifact downloads are implemented for Modal jobs.

## Install or share the skill

The distributable folder is:

```text
.agents/skills/autofoundry/
├── SKILL.md
├── LICENSE
├── agents/openai.yaml
└── references/api.md
```

Install that complete folder through your agent's skill installer, or copy it into the
agent's supported skills directory under the name `autofoundry`. Repository-local
agents that support `.agents/skills` can use it directly. The skill is also portable
without the optional `agents/openai.yaml` UI metadata.

Install the Python dependency from the **same reviewed commit** as the skill. While the
PR is unmerged, do not assume the default branch or PyPI release has the new API:

```bash
uv pip install 'autofoundry[modal] @ git+https://github.com/shea256/autofoundry.git@COMMIT_SHA'
```

Replace `COMMIT_SHA` with the actual Git commit. In a checkout use
`uv sync --extra modal`. The skill's reference explains installation when used outside
the repository; it does not depend on an absolute path or another installed skill.

To prepare a shareable archive after committing the matching code:

```bash
python scripts/package_skill.py /tmp/autofoundry-skill.zip
```

The ZIP contains only the skill, license, supported references/metadata, and generated
`references/revision.md` with a pinned package-install command. It excludes workspace
config, environment files and credentials. Packaging does not upload or publish a
release. You can distribute the archive or link others to the committed skill folder;
no registry publication has been performed.

## Validation

Offline tests cover the API's lack of CLI imports/output, structured provider failures,
constraints and credential redaction, one-attempt host creation, exact-ID cleanup, SSH
verification, execution/results/timeouts, and portable archive contents. Existing CLI
and Modal tests also run. No paid GPU or live account operations are needed for these
checks. Live host/Modal validation remains separate and requires explicit authorization.
