"""Lambda Labs GPU cloud provider."""

from __future__ import annotations

import re
import time

import httpx

from autofoundry.models import (
    GpuOffer,
    InstanceConfig,
    InstanceInfo,
    InstanceStatus,
    ProviderName,
    SshConnectionInfo,
    VolumeInfo,
)


class LambdaLabsProvider:
    """Lambda Labs API client implementing the CloudProvider protocol."""

    name = "lambdalabs"
    BASE_URL = "https://cloud.lambdalabs.com/api/v1"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Lambda Labs API key is required")
        self._api_key = api_key
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            auth=(api_key, ""),  # Basic auth: API key as username, empty password
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )
        self._ssh_key_name: str | None = None

    def _ensure_ssh_key(self, public_key: str) -> str:
        """Register SSH public key and return the key name."""
        if self._ssh_key_name:
            return self._ssh_key_name

        if not public_key:
            raise ValueError("Lambda Labs requires an SSH public key to launch instances")

        # Check if key already exists
        resp = self._client.get("/ssh-keys")
        resp.raise_for_status()
        existing = resp.json().get("data", [])

        for key_info in existing:
            if key_info.get("public_key", "").strip() == public_key.strip():
                self._ssh_key_name = key_info["name"]
                return self._ssh_key_name

        # Register new key
        key_name = "autofoundry"
        resp = self._client.post(
            "/ssh-keys",
            json={"name": key_name, "public_key": public_key},
        )
        if resp.status_code >= 300:
            # Key name might already exist with a different key, try unique name
            import hashlib

            key_hash = hashlib.sha256(public_key.encode()).hexdigest()[:8]
            key_name = f"autofoundry-{key_hash}"
            resp = self._client.post(
                "/ssh-keys",
                json={"name": key_name, "public_key": public_key},
            )
            resp.raise_for_status()

        self._ssh_key_name = key_name
        return key_name

    def validate_key(self) -> bool:
        try:
            resp = self._client.get("/instances")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def list_gpu_offers(self, gpu_type: str | None = None) -> list[GpuOffer]:
        resp = self._client.get("/instance-types")
        resp.raise_for_status()
        data = resp.json().get("data", {})

        offers = []
        for type_name, info in data.items():
            instance_type = info.get("instance_type", {})
            description = instance_type.get("description", type_name)
            gpu_desc = instance_type.get("gpu_description", "")

            # Client-side GPU type filter
            search_target = f"{description} {gpu_desc}".upper()
            if gpu_type and gpu_type.upper() not in search_target:
                continue

            price = instance_type.get("price_cents_per_hour", 0) / 100.0
            if price <= 0:
                continue

            gpu_count = instance_type.get("specs", {}).get("gpus", 1)

            # VRAM isn't in specs — parse from description e.g. "2x H100 (80 GB SXM5)"
            vram_match = re.search(r"\((\d+)\s*GB", description)
            gpu_ram = int(vram_match.group(1)) if vram_match else 0

            # Use description (includes count prefix like "2x") as the display name
            display_gpu = description

            # Each region is a separate offer
            regions = info.get("regions_with_capacity_available", [])

            if not regions:
                # Skip GPU types with no available regions — can't launch them
                continue
            else:
                for region in regions:
                    region_name = region.get("name", "unknown")
                    region_desc = region.get("description", region_name)
                    offers.append(GpuOffer(
                        provider=ProviderName.LAMBDALABS,
                        offer_id=type_name,
                        gpu_type=display_gpu,
                        gpu_count=gpu_count,
                        gpu_ram_gb=gpu_ram,
                        price_per_hour=price,
                        region=region_desc,
                        availability=1,
                        metadata={"region_name": region_name},
                    ))

        return offers

    def list_volumes(self) -> list[VolumeInfo]:
        """List all persistent filesystems."""
        resp = self._client.get("/file-systems")
        resp.raise_for_status()
        filesystems = resp.json().get("data", [])
        return [
            VolumeInfo(
                provider=ProviderName.LAMBDALABS,
                volume_id=fs["id"],
                name=fs.get("name", ""),
                size_gb=fs.get("bytes_used", 0) // (1024**3),
                region=fs.get("region", {}).get("name", ""),
                mount_path="/lambda/nfs/persistent-storage",
            )
            for fs in filesystems
        ]

    def create_volume(self, name: str, region: str) -> VolumeInfo:
        """Create a new persistent filesystem."""
        resp = self._client.post(
            "/file-systems",
            json={"name": name, "region": region},
        )
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Lambda Labs create filesystem failed: {resp.status_code} {resp.text}"
            )
        fs = resp.json().get("data", {})
        return VolumeInfo(
            provider=ProviderName.LAMBDALABS,
            volume_id=fs["id"],
            name=name,
            size_gb=0,
            region=region,
            mount_path="/lambda/nfs/persistent-storage",
        )

    def create_instance(self, config: InstanceConfig) -> InstanceInfo:
        # Ensure SSH key is registered
        ssh_key_name = self._ensure_ssh_key(config.ssh_public_key)

        payload: dict = {
            "instance_type_name": config.offer_id,
            "ssh_key_names": [ssh_key_name],
        }

        # Lambda Labs requires a region
        region = config.metadata.get("region_name")
        if not region:
            raise ValueError(
                f"No region available for {config.gpu_type} on Lambda Labs. "
                "This GPU type may have no current capacity."
            )
        payload["region_name"] = region

        if config.name:
            payload["name"] = config.name

        # Attach filesystem if specified
        if config.volume_id:
            payload["file_system_names"] = [config.volume_id]

        resp = self._client.post("/instance-operations/launch", json=payload)
        if resp.status_code >= 300:
            raise httpx.HTTPStatusError(
                f"Lambda Labs launch failed ({resp.status_code}): {resp.text}",
                request=resp.request,
                response=resp,
            )

        data = resp.json().get("data", {})
        instance_ids = data.get("instance_ids", [])
        if not instance_ids:
            raise RuntimeError(f"Lambda Labs launch returned no instance IDs: {data}")

        instance_id = instance_ids[0]

        return InstanceInfo(
            provider=ProviderName.LAMBDALABS,
            instance_id=instance_id,
            name=config.name,
            status=InstanceStatus.STARTING,
            gpu_type=config.gpu_type,
            gpu_count=config.gpu_count,
        )

    def get_instance(self, instance_id: str) -> InstanceInfo:
        resp = self._client.get(f"/instances/{instance_id}")
        resp.raise_for_status()
        instance = resp.json().get("data", {})

        status_map = {
            "active": InstanceStatus.RUNNING,
            "booting": InstanceStatus.STARTING,
            "unhealthy": InstanceStatus.ERROR,
            "terminated": InstanceStatus.DELETED,
        }
        status = status_map.get(instance.get("status", ""), InstanceStatus.PENDING)

        ssh = None
        ip = instance.get("ip")
        if ip:
            ssh = SshConnectionInfo(host=ip, port=22, username="ubuntu")

        return InstanceInfo(
            provider=ProviderName.LAMBDALABS,
            instance_id=instance_id,
            name=instance.get("name", ""),
            status=status,
            gpu_type=instance.get("instance_type", {}).get("gpu_description", ""),
            gpu_count=instance.get("instance_type", {}).get("specs", {}).get("gpus", 1),
            ssh=ssh,
        )

    def wait_until_ready(self, instance_id: str, timeout: int = 300) -> InstanceInfo:
        deadline = time.time() + timeout
        delay = 5.0
        while time.time() < deadline:
            info = self.get_instance(instance_id)
            if info.status == InstanceStatus.RUNNING and info.ssh:
                return info
            if info.status in (InstanceStatus.ERROR, InstanceStatus.DELETED):
                raise RuntimeError(
                    f"Lambda Labs instance {instance_id} entered state: {info.status.value}"
                )
            time.sleep(min(delay, deadline - time.time()))
            delay = min(delay * 1.5, 30.0)
        raise TimeoutError(
            f"Lambda Labs instance {instance_id} not ready within {timeout}s"
        )

    def get_ssh_info(self, instance_id: str) -> SshConnectionInfo:
        info = self.get_instance(instance_id)
        if info.ssh is None:
            raise RuntimeError(
                f"No SSH info available for Lambda Labs instance {instance_id}"
            )
        return info.ssh

    def delete_instance(self, instance_id: str) -> None:
        resp = self._client.post(
            "/instance-operations/terminate",
            json={"instance_ids": [instance_id]},
        )
        resp.raise_for_status()
