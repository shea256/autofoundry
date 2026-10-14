"""Abstract base for GPU cloud providers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from autofoundry.models import GpuOffer, InstanceConfig, InstanceInfo, SshConnectionInfo

if TYPE_CHECKING:
    from autofoundry.providers.modal import ModalJobSpec


@runtime_checkable
class CloudProvider(Protocol):
    """Uniform interface for GPU cloud providers."""

    name: str

    def validate_key(self) -> bool:
        """Validate the API key by making a lightweight API call."""
        ...

    def list_gpu_offers(self, gpu_type: str | None = None) -> list[GpuOffer]:
        """Query available GPU offers, optionally filtered by type."""
        ...

    def create_instance(self, config: InstanceConfig) -> InstanceInfo:
        """Provision a new GPU instance."""
        ...

    def get_instance(self, instance_id: str) -> InstanceInfo:
        """Get current info for an instance."""
        ...

    def wait_until_ready(self, instance_id: str, timeout: int = 300) -> InstanceInfo:
        """Poll until instance is running and SSH-accessible."""
        ...

    def get_ssh_info(self, instance_id: str) -> SshConnectionInfo:
        """Extract SSH connection details for a running instance."""
        ...

    def delete_instance(self, instance_id: str) -> None:
        """Terminate and delete an instance."""
        ...


@runtime_checkable
class ServerlessProvider(Protocol):
    """Catalog and bounded jobs, without persistent host or SSH semantics."""

    name: str

    def list_gpu_offers(self, gpu_type: str | None = None) -> list[GpuOffer]: ...

    async def run_job(self, spec: ModalJobSpec, directory: Path) -> dict:
        """Run one bounded job, persist results, and attempt scoped cleanup."""
        ...

    async def cleanup_job(self, directory: Path) -> None:
        """Terminate only the resource recorded for this job."""
        ...
