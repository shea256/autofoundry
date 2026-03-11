"""Data models for autofoundry."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ProviderName(StrEnum):
    RUNPOD = "runpod"
    VASTAI = "vastai"
    PRIMEINTELLECT = "primeintellect"
    LAMBDALABS = "lambdalabs"


class SessionStatus(StrEnum):
    CONFIGURING = "configuring"
    PLANNING = "planning"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    PAUSED = "paused"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"


class InstanceStatus(StrEnum):
    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    DELETED = "deleted"


class ExperimentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GpuOffer(BaseModel):
    """A GPU offering from a cloud provider."""

    provider: ProviderName
    offer_id: str
    gpu_type: str
    gpu_count: int
    gpu_ram_gb: float
    price_per_hour: float
    region: str | None = None
    inet_down_mbps: float = 0.0
    availability: int = 1
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Provider-specific fields needed for instance creation",
    )


class InstanceConfig(BaseModel):
    """Configuration for creating a cloud instance."""

    name: str
    gpu_type: str
    gpu_count: int = 1
    image: str = "pytorch/pytorch:latest"
    disk_gb: int = 50
    ssh_public_key: str = ""
    offer_id: str = ""  # Provider-specific offer/GPU ID for creation
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Provider-specific fields passed through from GpuOffer",
    )


class SshConnectionInfo(BaseModel):
    """SSH connection details for a running instance."""

    host: str
    port: int = 22
    username: str = "root"
    key_path: str = ""


class InstanceInfo(BaseModel):
    """Runtime info for a provisioned instance."""

    provider: ProviderName
    instance_id: str
    name: str
    status: InstanceStatus
    gpu_type: str
    gpu_count: int = 1
    price_per_hour: float = 0.0
    ssh: SshConnectionInfo | None = None
    created_at: datetime | None = None


class ExperimentResult(BaseModel):
    """Parsed results from a single experiment run."""

    experiment_id: int
    instance_id: str
    run_index: int
    status: ExperimentStatus
    metrics: dict[str, float] = Field(default_factory=dict)
    raw_output: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    exit_code: int | None = None


class ProvisioningPlan(BaseModel):
    """Plan for which GPU offers to provision."""

    offers: list[tuple[GpuOffer, int]] = Field(
        default_factory=list,
        description="List of (offer, count) pairs",
    )
    total_experiments: int = 0
    script_path: str = ""

    @property
    def total_instances(self) -> int:
        return sum(count for _, count in self.offers)

    @property
    def estimated_cost_per_hour(self) -> float:
        return sum(offer.price_per_hour * count for offer, count in self.offers)


class Session(BaseModel):
    """Top-level session tracking an autofoundry operation."""

    session_id: str
    status: SessionStatus = SessionStatus.CONFIGURING
    script_path: str = ""
    total_experiments: int = 0
    gpu_type: str = "H100"
    created_at: datetime = Field(default_factory=datetime.now)
    instances: list[InstanceInfo] = Field(default_factory=list)
    results: list[ExperimentResult] = Field(default_factory=list)
