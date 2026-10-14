"""Non-interactive Python API for agents and other automation.

No CLI imports, dotenv loading, prompts or console output. Cloud mutations are
explicit calls; constructing a client, catalog discovery and planning allocate nothing.
"""

from __future__ import annotations

import asyncio
import math
import os
import shlex
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr

from autofoundry.defaults import PROVIDER_IMAGES
from autofoundry.gpu_filter import GpuQuery, filter_by_vram, gpu_name_matches
from autofoundry.metrics import parse_metrics
from autofoundry.models import (
    GpuOffer,
    InstanceConfig,
    InstanceInfo,
    InstanceStatus,
    ProviderName,
)
from autofoundry.providers import get_provider
from autofoundry.providers.modal import ModalJobSpec, ModalProvider, select_offer

__all__ = [
    "ApiError",
    "Autofoundry",
    "DiscoveryResult",
    "GpuQuery",
    "HostPlan",
    "ModalJobSpec",
    "ProviderInventory",
    "ProviderName",
    "ScriptResult",
    "run_host_script",
]


class ApiError(RuntimeError):
    """Safe error. Provider exception payloads and credentials are never included."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ProviderInventory(BaseModel):
    provider: ProviderName
    offers: list[GpuOffer] = Field(default_factory=list)
    error: str | None = None


class DiscoveryResult(BaseModel):
    providers: list[ProviderInventory]

    @property
    def offers(self) -> list[GpuOffer]:
        """Flattened price-sorted offers; inspect price_basis before comparing costs."""
        return sorted((o for p in self.providers for o in p.offers), key=lambda o: o.price_per_hour)


class HostPlan(BaseModel):
    """Reviewable local request; no credential fields and no resource allocation."""

    offer: GpuOffer
    config: InstanceConfig


class ScriptResult(BaseModel):
    provider: ProviderName
    instance_id: str
    status: str = "failed"
    exit_code: int | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    error: str | None = None


class Autofoundry:
    """Use explicit credentials, or from_env() for the existing host API-key names.

    Modal tokens remain entirely managed by the official SDK. Client repr and discovery
    responses never contain credentials. No config files are read or written here.
    """

    def __init__(
        self,
        credentials: dict[ProviderName, SecretStr | str] | None = None,
        *,
        min_bandwidth_mbps: float = 5000,
    ):
        if credentials and ProviderName.MODAL in credentials:
            raise ApiError("modal_auth", "Use official Modal token configuration")
        self._credentials = {
            ProviderName(name): value if isinstance(value, SecretStr) else SecretStr(value)
            for name, value in (credentials or {}).items()
        }
        self._min_bandwidth = min_bandwidth_mbps

    @classmethod
    def from_env(cls) -> Autofoundry:
        """Read host API keys from process environment; never load repository .env files."""
        keys = {}
        for name in ProviderName:
            if name != ProviderName.MODAL:
                value = os.environ.get(f"{name.value.upper()}_API_KEY")
                if value:
                    keys[name] = SecretStr(value)
        return cls(keys)

    def _provider(self, name: ProviderName):
        if name == ProviderName.MODAL:
            return get_provider(name)
        credential = self._credentials.get(name)
        if not credential or not credential.get_secret_value():
            raise ApiError("missing_credentials", f"No credentials configured for {name.value}")
        try:
            return get_provider(
                name, credential.get_secret_value(), min_bandwidth_mbps=self._min_bandwidth
            )
        except Exception:
            raise ApiError("provider_setup_failed", "Provider initialization failed") from None

    def discover(
        self,
        query: GpuQuery | None = None,
        *,
        providers: list[ProviderName] | None = None,
    ) -> DiscoveryResult:
        """Read inventory concurrently; one provider's failure cannot hide another's offers.

        Defaults to credentialed host providers plus the public Modal catalog. Pass an
        explicit provider list to bound which accounts are queried. An empty list queries none.
        """
        query = query or GpuQuery()
        names = list(
            dict.fromkeys(
                ProviderName(p)
                for p in (
                    providers if providers is not None else [*self._credentials, ProviderName.MODAL]
                )
            )
        )

        def fetch(name):
            try:
                provider = self._provider(name)
                if name == ProviderName.VASTAI and query.vram_min is not None:
                    offers = provider.list_gpu_offers(query.gpu_type, vram_min=query.vram_min)
                else:
                    offers = provider.list_gpu_offers(query.gpu_type)
                offers = filter_by_vram(offers, query.vram_min, query.vram_max)
                if query.single_gpu:
                    offers = [o for o in offers if o.gpu_count == 1]
                if query.gpu_type:
                    offers = [o for o in offers if gpu_name_matches(query.gpu_type, o.gpu_type)]
                if query.gpu_patterns:
                    offers = [
                        o
                        for o in offers
                        if any(gpu_name_matches(p, o.gpu_type) for p in query.gpu_patterns)
                    ]
                return ProviderInventory(provider=name, offers=offers)
            except ApiError as exc:
                return ProviderInventory(provider=name, error=exc.code)
            except Exception:
                return ProviderInventory(provider=name, error="discovery_failed")

        with ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
            return DiscoveryResult(providers=list(pool.map(fetch, names)))

    @staticmethod
    def plan_modal(
        query: GpuQuery, *, script: str, gpu_count: int = 1, **resources
    ) -> ModalJobSpec:
        """Local catalog selection. The returned spec exposes estimate() and selector."""
        offer = select_offer(query, gpu_count)
        return ModalJobSpec(script=script, gpu=offer.gpu_type, gpu_count=gpu_count, **resources)

    async def run_modal(self, spec: ModalJobSpec, directory: Path) -> dict:
        """Allocate one bounded Sandbox, run once, persist results and attempt cleanup."""
        return await ModalProvider().run_job(spec, Path(directory))

    async def cleanup_modal(self, directory: Path) -> None:
        """Retry cleanup of the exact recorded Sandbox; retain App and Volume resources."""
        await ModalProvider().cleanup_job(Path(directory))

    @staticmethod
    def plan_host(
        offer: GpuOffer,
        *,
        name: str,
        ssh_public_key: str,
        image: str | None = None,
        disk_gb: int = 50,
        volume_id: str = "",
        volume_region: str = "",
    ) -> HostPlan:
        """Preserve the selected offer's provider, GPU count and placement metadata."""
        if offer.provider == ProviderName.MODAL or offer.execution_kind != "host":
            raise ApiError("serverless_offer", "Use plan_modal/run_modal for serverless jobs")
        if not name or not ssh_public_key or disk_gb < 1:
            raise ApiError(
                "invalid_request", "Name, SSH public key and positive disk size required"
            )
        if volume_id and offer.provider not in (ProviderName.RUNPOD, ProviderName.LAMBDALABS):
            raise ApiError("unsupported_volume", "This provider does not support attached volumes")
        return HostPlan(
            offer=offer,
            config=InstanceConfig(
                name=name,
                gpu_type=offer.gpu_type,
                gpu_count=offer.gpu_count,
                offer_id=offer.offer_id,
                metadata=dict(offer.metadata),
                image=image if image is not None else PROVIDER_IMAGES[offer.provider],
                disk_gb=disk_gb,
                ssh_public_key=ssh_public_key,
                volume_id=volume_id,
                volume_region=volume_region,
            ),
        )

    def create_host(self, plan: HostPlan) -> InstanceInfo:
        """Allocate exactly the reviewed offer once. May also register the supplied SSH key.

        Persist the returned ID immediately. A failed/ambiguous create is never retried:
        reconcile the named resource in the provider before submitting another request.
        """
        offer, config = plan.offer, plan.config
        if offer.provider == ProviderName.MODAL or offer.execution_kind != "host":
            raise ApiError("serverless_offer", "Use run_modal for serverless jobs")
        if (config.offer_id, config.gpu_type, config.gpu_count, config.metadata) != (
            offer.offer_id,
            offer.gpu_type,
            offer.gpu_count,
            offer.metadata,
        ):
            raise ApiError("plan_changed", "GPU/offer/placement differs from the reviewed offer")
        provider = self._provider(offer.provider)
        try:
            return provider.create_instance(config)
        except Exception:
            raise ApiError(
                "creation_unconfirmed", "Host creation unconfirmed; do not retry blindly"
            ) from None

    def get_host(self, provider: ProviderName, instance_id: str) -> InstanceInfo:
        backend = self._host_provider(provider, instance_id)
        try:
            return backend.get_instance(instance_id)
        except Exception:
            raise ApiError("status_failed", "Host status lookup failed") from None

    def wait_host(self, instance: InstanceInfo, *, timeout: float = 300) -> InstanceInfo:
        """Poll for running+SSH info without terminal output or offer substitutions.

        Timeout does not terminate the host. Individual adapter HTTP timeouts still apply.
        """
        if not math.isfinite(timeout) or timeout <= 0:
            raise ApiError("invalid_timeout", "Readiness timeout must be positive")
        deadline = time.monotonic() + timeout
        while True:
            current = self.get_host(instance.provider, instance.instance_id)
            if current.status == InstanceStatus.RUNNING and current.ssh:
                return current
            if current.status in (
                InstanceStatus.ERROR,
                InstanceStatus.DELETED,
                InstanceStatus.STOPPED,
            ):
                raise ApiError("host_unavailable", "Host entered a non-running terminal state")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ApiError(
                    "readiness_timeout", "Host readiness timed out; host may still be billed"
                )
            time.sleep(min(5, remaining))

    def terminate_host(self, provider: ProviderName, instance_id: str) -> None:
        """Request deletion of one explicit host; does not delete persistent volumes."""
        backend = self._host_provider(provider, instance_id)
        try:
            backend.delete_instance(instance_id)
        except Exception:
            raise ApiError(
                "cleanup_unconfirmed", "Host termination unconfirmed; inspect this ID"
            ) from None

    def _host_provider(self, provider: ProviderName, instance_id: str):
        provider = ProviderName(provider)
        if provider == ProviderName.MODAL or not instance_id:
            raise ApiError("invalid_host", "A host provider and an exact instance ID are required")
        return self._provider(provider)


async def run_host_script(
    instance: InstanceInfo,
    script: Path,
    *,
    ssh_key_path: Path,
    directory: Path,
    timeout: float = 3600,
    workdir: str = "/workspace",
    known_hosts: Path | None = None,
) -> ScriptResult:
    """Run a script on an existing SSH host and persist bounded output and numeric metrics.

    No credentials/environment are forwarded. Host-key verification is mandatory; None
    uses ~/.ssh/known_hosts. This never terminates the host: the caller owns that lifecycle.
    """
    import asyncssh

    if instance.provider == ProviderName.MODAL or instance.ssh is None:
        raise ApiError("invalid_host", "An SSH host is required")
    script = Path(script).expanduser().resolve()
    if (
        not script.is_file()
        or not math.isfinite(timeout)
        or timeout <= 0
        or not workdir.startswith("/")
    ):
        raise ApiError(
            "invalid_request", "Provide a local script, positive timeout and absolute workdir"
        )
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    result = ScriptResult(provider=instance.provider, instance_id=instance.instance_id)
    ssh = instance.ssh
    remote = f"/tmp/autofoundry-{uuid4().hex}.sh"
    output = directory / "output.log"
    output.touch()
    size = 0

    async def execute():
        nonlocal size
        async with asyncssh.connect(
            ssh.host,
            port=ssh.port,
            username=ssh.username,
            client_keys=[str(Path(ssh_key_path).expanduser())],
            known_hosts=str(
                Path(known_hosts).expanduser()
                if known_hosts
                else Path.home() / ".ssh" / "known_hosts"
            ),
            config=None,
            agent_path=None,
            password_auth=False,
            kbdint_auth=False,
            connect_timeout=min(30, timeout),
        ) as connection:
            async with connection.start_sftp_client() as sftp:
                try:
                    await sftp.put(str(script), remote)
                    command = (
                        f"cd -- {shlex.quote(workdir)} && exec bash {shlex.quote(remote)} 2>&1"
                    )
                    async with connection.create_process(command, env={}) as process:

                        async def drain(reader):
                            nonlocal size
                            while chunk := await reader.read(65536):
                                size += len(chunk.encode())
                                if size > 4 * 1024 * 1024:
                                    raise ApiError("output_limit", "Host output exceeded 4 MiB")
                                with output.open("a") as log:
                                    log.write(chunk)

                        try:
                            async with asyncio.TaskGroup() as tasks:
                                tasks.create_task(drain(process.stdout))
                                tasks.create_task(drain(process.stderr))
                            await process.wait_closed()
                            result.exit_code = process.exit_status
                        finally:
                            if process.exit_status is None:
                                process.terminate()
                finally:
                    try:
                        await asyncio.wait_for(sftp.remove(remote), 10)
                    except Exception:
                        pass  # Temporary script removal must not hide the experiment outcome.
        result.status = "completed" if result.exit_code == 0 else "failed"
        result.metrics = parse_metrics(output.read_text().splitlines())

    try:
        await asyncio.wait_for(execute(), timeout)
    except asyncio.CancelledError:
        result.error = "interrupted"
        raise
    except Exception:
        # Avoid SSH error text, command arguments or remote data in error diagnostics.
        result.error = "execution_failed_or_timed_out"
    finally:
        (directory / "result.json").write_text(result.model_dump_json(indent=2) + "\n")
    return result
