"""Modal's published catalog and bounded Sandbox jobs (never SSH hosts).

Sources and snapshot policy: docs/modal.md. No SDK import or auth during discovery.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from autofoundry.gpu_filter import GpuQuery, filter_by_vram, gpu_name_matches
from autofoundry.metrics import parse_metrics
from autofoundry.models import GpuOffer, ProviderName

CATALOG_DATE = "2026-10-14"
# selector: (per-GPU VRAM GB, USD/GPU/second, documented max GPU count)
CATALOG = {
    "T4": (16, 0.000164, 8),
    "L4": (24, 0.000222, 8),
    "A10": (24, 0.000306, 4),
    "L40S": (48, 0.000542, 8),
    "A100-40GB": (40, 0.000583, 8),
    "A100-80GB": (80, 0.000694, 8),
    "RTX-PRO-6000": (96, 0.000842, 1),
    "H100": (80, 0.001097, 8),
    "H200": (141, 0.001261, 8),
    "B200": (180, 0.001736, 8),
    "B300": (288, 0.001972, 8),
}
# Sandbox rates, NOT Function CPU/RAM rates. CPU units are physical cores.
CPU_SECOND = 0.00003942
RAM_GIB_SECOND = 0.00000667
VOLUME_GIB_MONTH = 0.09
EGRESS_GIB = 0.04
BROAD_REGIONS = {"us", "eu", "ap"}
NARROW_REGIONS = {
    "us-east",
    "us-central",
    "us-south",
    "us-west",
    "eu-west",
    "eu-north",
    "eu-south",
    "ap-northeast",
    "ap-southeast",
    "ap-south",
    "ap-melbourne",
    "jp",
    "au",
    "uk",
    "ca",
    "me",
    "sa",
    "af",
    "mx",
}
DEFAULT_IMAGE = "nvidia/cuda:13.1.0-runtime-ubuntu24.04"
API_TIMEOUT = 60
CLEANUP_TIMEOUT = 30
MAX_OUTPUT = 4 * 1024 * 1024


class ModalError(RuntimeError):
    """Safe public error: never includes an SDK exception or credentials."""


class ModalJobSpec(BaseModel):
    script: str
    app_name: str = "autofoundry"
    gpu: str = "H100"
    gpu_count: int = Field(default=1, ge=1, le=8)
    cpu: float = Field(default=2, ge=0.125, le=64, allow_inf_nan=False)
    memory_mib: int = Field(default=16384, ge=128, le=1048576)
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    region: str | None = None
    image: str = DEFAULT_IMAGE
    volume: str | None = None  # Existing named Volume only; mounted at /workspace.
    artifacts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request(self):
        if self.gpu not in CATALOG:
            raise ValueError("Select an explicit catalog GPU; fallback lists/upgrades are disabled")
        if self.gpu_count > CATALOG[self.gpu][2]:
            raise ValueError("GPU count exceeds the documented limit for this GPU")
        if self.region and self.region not in BROAD_REGIONS | NARROW_REGIONS:
            raise ValueError("Unsupported Modal region; use an exact documented region")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.app_name):
            raise ValueError("Invalid Modal App name")
        for path in self.artifacts:
            if not path.startswith("/workspace/") or ".." in Path(path).parts:
                raise ValueError("Artifacts must be explicit files under /workspace without '..'")
        if len({Path(p).name for p in self.artifacts}) != len(self.artifacts):
            raise ValueError("Artifact basenames must be unique")
        return self

    @property
    def selector(self) -> str:
        # H100! opts out of automatic H200 upgrades; explicit A100 memory variants.
        gpu = "H100!" if self.gpu == "H100" else self.gpu
        return f"{gpu}:{self.gpu_count}"

    def estimate(self) -> dict:
        multiplier = 1.15 if self.region in BROAD_REGIONS else 1.75 if self.region else 1.0
        parts = {
            "gpu_per_hour": CATALOG[self.gpu][1] * self.gpu_count * 3600,
            "cpu_per_hour": self.cpu * CPU_SECOND * 3600,
            "ram_per_hour": self.memory_mib / 1024 * RAM_GIB_SECOND * 3600,
        }
        compute = sum(parts.values()) * multiplier
        return {
            **parts,
            "region_multiplier": multiplier,
            "compute_per_hour": compute,
            "compute_for_timeout": compute * self.timeout_seconds / 3600,
            "volume_per_gib_month": VOLUME_GIB_MONTH,
            "egress_per_gib": EGRESS_GIB,
            "total_cost": None,
            "catalog_date": CATALOG_DATE,
            "capacity": "unknown",
            "notes": "Compute estimate only; includes GPU, CPU and RAM with equal request/limit. "
            "Storage, egress, image builds, startup/collection time, plan fees and taxes "
            "can add charges. Credits/free allowances not assumed. Not a billing cap.",
        }


class ModalProvider:
    name = "modal"

    def __init__(self, sdk=None):
        self._sdk_override = sdk

    def _sdk(self):
        if self._sdk_override is not None:
            return self._sdk_override
        try:
            return importlib.import_module("modal")
        except ImportError:
            raise ModalError("Install autofoundry[modal] for authenticated execution") from None

    def list_gpu_offers(self, gpu_type: str | None = None) -> list[GpuOffer]:
        offers = []
        for gpu, (vram, _, maximum) in CATALOG.items():
            if gpu_type and not modal_gpu_matches(gpu_type, gpu):
                continue
            for count in range(1, maximum + 1):
                spec = ModalJobSpec(script="", gpu=gpu, gpu_count=count)
                offers.append(
                    GpuOffer(
                        provider=ProviderName.MODAL,
                        offer_id=spec.selector,
                        gpu_type=gpu,
                        gpu_count=count,
                        gpu_ram_gb=vram,
                        price_per_hour=spec.estimate()["compute_per_hour"],
                        availability=None,
                        execution_kind="serverless",
                        price_basis="catalog_compute",
                        metadata={
                            "catalog_date": CATALOG_DATE,
                            "source": "https://modal.com/pricing",
                            "cpu_cores": "2",
                            "memory_mib": "16384",
                        },
                    )
                )
        return sorted(offers, key=lambda offer: offer.price_per_hour)

    async def _authenticate(self):
        try:
            # Official SDK resolves active profile, MODAL_CONFIG_PATH and token env vars.
            # Never copy tokens into Autofoundry config, job manifests or workload env.
            return await asyncio.wait_for(self._sdk().Client.from_env.aio(), API_TIMEOUT)
        except ModalError:
            raise
        except Exception:
            raise ModalError(
                "Modal authentication failed; check official token/profile setup"
            ) from None

    async def validate_auth(self) -> bool:
        await self._authenticate()
        return True

    async def cleanup_job(self, directory: Path) -> None:
        """One exact job only. Never enumerate/delete Apps, Volumes or other Sandboxes."""
        record = json.loads((directory / "job.json").read_text())
        if not re.fullmatch(r"af-[0-9a-f]{32}", record.get("job_id", "")):
            raise ModalError("Invalid Autofoundry job record")
        if record.get("cleanup") in ("terminated", "not_created"):
            return
        sdk = self._sdk()
        client = await self._authenticate()

        async def terminate():
            if record.get("sandbox_id"):
                sandbox = await sdk.Sandbox.from_id.aio(record["sandbox_id"], client=client)
            else:
                # Recover an ambiguous create response by exact, pre-journaled name.
                sandbox = await sdk.Sandbox.from_name.aio(
                    record["app_name"],
                    record["job_id"],
                    client=client,
                )
            tags = await sandbox.get_tags.aio()
            if tags.get("autofoundry_job") != record["job_id"]:
                raise ModalError("Sandbox ownership check failed; cleanup refused")
            await sandbox.terminate.aio(wait=True)

        try:
            await asyncio.wait_for(terminate(), CLEANUP_TIMEOUT)
        except Exception:
            raise ModalError(
                "Modal cleanup unconfirmed; retry this job or inspect it in Modal"
            ) from None
        record["cleanup"] = "terminated"
        _save(directory, record)

    async def run_job(self, spec: ModalJobSpec, directory: Path) -> dict:
        """One attempt; gather results before termination, with a remote lifetime backstop."""
        # Validate local inputs before authenticating or creating anything.
        script = Path(spec.script).expanduser().resolve()
        if not script.is_file():
            raise ModalError("Experiment script must be a local file")
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        record = {
            "job_id": f"af-{uuid4().hex}",
            "app_name": spec.app_name,
            "sandbox_id": None,
            "status": "starting",
            "created_at": datetime.now(UTC).isoformat(),
            "cleanup": "not_created",
            "exit_code": None,
            "metrics": {},
            "spec": spec.model_dump(),
            "estimate": spec.estimate(),
        }
        _save(directory, record)
        sandbox = None
        creation_attempted = False
        try:
            sdk = self._sdk()
            client = await self._authenticate()
            app = await asyncio.wait_for(
                sdk.App.lookup.aio(
                    spec.app_name,
                    create_if_missing=False,
                    client=client,
                ),
                API_TIMEOUT,
            )
            volumes = {}
            if spec.volume:
                volume = sdk.Volume.from_name(spec.volume, create_if_missing=False)
                await asyncio.wait_for(volume.hydrate.aio(client=client), API_TIMEOUT)
                volumes["/workspace"] = volume
            image = sdk.Image.from_registry(spec.image)
            creation_attempted = True
            record["cleanup"] = "pending"
            _save(directory, record)
            sandbox = await asyncio.wait_for(
                sdk.Sandbox.create.aio(
                    "sleep",
                    "infinity",
                    app=app,
                    name=record["job_id"],
                    tags={"autofoundry_job": record["job_id"]},
                    image=image,
                    gpu=spec.selector,
                    cpu=(spec.cpu, spec.cpu),
                    memory=(spec.memory_mib, spec.memory_mib),
                    region=spec.region,
                    timeout=spec.timeout_seconds,
                    runtime="gvisor",
                    volumes=volumes,
                    env={"PYTHONUNBUFFERED": "1", "AUTOFOUNDRY_IMAGE": spec.image},
                    client=client,
                    verbose=False,
                ),
                API_TIMEOUT,
            )
            record.update(sandbox_id=sandbox.object_id, status="running")
            _save(directory, record)  # Durable ID before upload/execution.

            async def execute():
                await sandbox.filesystem.make_directory.aio("/workspace")
                await sandbox.filesystem.copy_from_local.aio(script, "/tmp/autofoundry.sh")
                # Record observed hardware separately from user metrics for controlled comparisons.
                probe = await sandbox.exec.aio(
                    "nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader",
                    timeout=30,
                )
                hardware, _ = await asyncio.gather(probe.stdout.read.aio(), probe.stderr.read.aio())
                await probe.wait.aio()
                if probe.returncode != 0:
                    raise ModalError("Unable to verify allocated GPU hardware")
                record["hardware"] = hardware
                _save(directory, record)
                verify_hardware(spec, hardware)
                proc = await sandbox.exec.aio(
                    "bash",
                    "-c",
                    "exec bash /tmp/autofoundry.sh 2>&1",
                    workdir="/workspace",
                    timeout=spec.timeout_seconds,
                )
                output = []
                size = 0
                (directory / "output.log").touch()
                async for chunk in proc.stdout:
                    size += len(chunk.encode())
                    if size > MAX_OUTPUT:
                        raise ModalError("Output exceeded the 4 MiB collection limit")
                    output.append(chunk)
                    with (directory / "output.log").open("a") as log:
                        log.write(chunk)
                await proc.wait.aio()
                record["exit_code"] = proc.returncode
                text = "".join(output)
                (directory / "output.log").write_text(text)
                record["metrics"] = parse_metrics(text.splitlines())
                for remote in spec.artifacts:
                    await sandbox.filesystem.copy_to_local.aio(
                        remote,
                        directory / "artifacts" / Path(remote).name,
                    )
                record["status"] = "completed" if proc.returncode == 0 else "failed"

            await asyncio.wait_for(execute(), spec.timeout_seconds)
        except (asyncio.CancelledError, KeyboardInterrupt):
            record.update(status="interrupted", error="Job interrupted; no automatic retry")
            raise
        except ModalError as exc:
            record.update(status="failed", error=str(exc))
        except Exception:
            # SDK errors may contain authorization data or request payloads. Never persist them.
            record.update(
                status="failed", error="Modal operation failed or timed out; no automatic retry"
            )
        finally:
            if creation_attempted:
                try:
                    if sandbox is not None:
                        await asyncio.wait_for(sandbox.terminate.aio(wait=True), CLEANUP_TIMEOUT)
                        record["cleanup"] = "terminated"
                    else:
                        record["cleanup"] = "unconfirmed"
                except Exception:
                    record["cleanup"] = "unconfirmed"
            record["finished_at"] = datetime.now(UTC).isoformat()
            _save(directory, record)
        return record


def _save(directory: Path, record: dict) -> None:
    temporary = directory / "job.json.tmp"
    with temporary.open("w") as output:
        os.chmod(temporary, 0o600)
        output.write(json.dumps(record, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(directory / "job.json")


def verify_hardware(spec: ModalJobSpec, output: str) -> None:
    rows = [line.split(",") for line in output.splitlines() if line.strip()]
    family = spec.gpu.split("-")[0] if spec.gpu.startswith("A100") else spec.gpu
    family = family.replace("-", " ")
    expected = CATALOG[spec.gpu][0]
    if len(rows) != spec.gpu_count:
        raise ModalError("Allocated GPU count differs from the requested count")
    for row in rows:
        try:
            memory = float(row[1].strip().split()[0]) / 1024
            matches = bool(re.search(r"\b" + re.escape(family) + r"\b", row[0], re.I))
        except (IndexError, ValueError):
            raise ModalError("Unable to parse allocated GPU hardware") from None
        # nvidia-smi reports usable MiB; catalog GB can be decimal and ECC reserves memory.
        if not matches or not expected * 0.90 <= memory <= expected * 1.05:
            raise ModalError("Allocated GPU differs from the controlled comparison request")


def select_offer(query: GpuQuery, gpu_count: int = 1) -> GpuOffer:
    offers = ModalProvider().list_gpu_offers(query.gpu_type)
    offers = filter_by_vram(offers, query.vram_min, query.vram_max)
    offers = [o for o in offers if o.gpu_count == gpu_count]
    if query.gpu_patterns:
        offers = [
            o for o in offers if any(modal_gpu_matches(p, o.gpu_type) for p in query.gpu_patterns)
        ]
    if not offers:
        raise ModalError(
            "No Modal catalog GPU matches the requested family, per-GPU VRAM and count"
        )
    return offers[0]


def modal_gpu_matches(query: str, gpu: str) -> bool:
    """Respect exact named families (L4 must not accidentally match L40S)."""
    normalized = query.upper().replace(" ", "-")
    if normalized in CATALOG:
        return normalized == gpu
    if normalized == "A100":
        return gpu.startswith("A100-")
    return gpu_name_matches(query, gpu)
