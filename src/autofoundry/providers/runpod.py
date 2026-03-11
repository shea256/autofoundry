"""RunPod GPU cloud provider."""

from __future__ import annotations

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


class RunPodProvider:
    """RunPod API client implementing the CloudProvider protocol."""

    name = "runpod"
    BASE_URL = "https://rest.runpod.io/v1"
    GRAPHQL_URL = "https://api.runpod.io/graphql"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("RunPod API key is required")
        self._api_key = api_key
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._ssh_key_synced = False

    def _ensure_ssh_key(self, public_key: str) -> None:
        """Register SSH public key in RunPod account settings via GraphQL."""
        if self._ssh_key_synced or not public_key:
            return

        # Fetch existing keys
        gql_headers = {"Authorization": f"Bearer {self._api_key}"}
        resp = httpx.post(
            self.GRAPHQL_URL,
            json={"query": "query { myself { id pubKey } }"},
            headers=gql_headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        myself = data.get("data", {}).get("myself") or {}
        existing = myself.get("pubKey", "") or ""

        # Check if our key is already registered
        if public_key.strip() in existing:
            self._ssh_key_synced = True
            return

        # Append our key
        new_keys = existing.strip()
        if new_keys:
            new_keys += "\n\n"
        new_keys += public_key.strip()

        mutation = """
        mutation Mutation($input: UpdateUserSettingsInput) {
            updateUserSettings(input: $input) {
                id
            }
        }
        """
        resp = httpx.post(
            self.GRAPHQL_URL,
            json={
                "query": mutation,
                "variables": {"input": {"pubKey": new_keys}},
            },
            headers=gql_headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        self._ssh_key_synced = True

    def validate_key(self) -> bool:
        try:
            resp = self._client.get("/pods")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def list_gpu_offers(self, gpu_type: str | None = None) -> list[GpuOffer]:
        # RunPod uses GraphQL for GPU type queries
        query = """
        query GpuTypes {
            gpuTypes {
                id
                displayName
                memoryInGb
                secureCloud
                communityCloud
                lowestPrice {
                    minimumBidPrice
                    uninterruptablePrice
                }
                communityPrice
                securePrice
            }
        }
        """
        resp = httpx.post(
            self.GRAPHQL_URL,
            json={"query": query},
            headers={"api_key": self._api_key},
            timeout=30.0,
        )
        resp.raise_for_status()
        result = resp.json()

        gpu_types = result.get("data", {}).get("gpuTypes", [])

        offers = []
        for item in gpu_types:
            if item is None:
                continue
            type_id = item.get("id", "")
            display_name = item.get("displayName", type_id)

            if gpu_type and gpu_type.upper() not in display_name.upper():
                continue

            # Secure cloud pricing
            secure_price = item.get("securePrice")
            if secure_price and secure_price > 0:
                offers.append(GpuOffer(
                    provider=ProviderName.RUNPOD,
                    offer_id=f"{type_id}:SECURE",
                    gpu_type=display_name,
                    gpu_count=1,
                    gpu_ram_gb=item.get("memoryInGb", 0),
                    price_per_hour=secure_price,
                    region="SECURE",
                    availability=1 if item.get("secureCloud") else 0,
                ))

            # Community cloud pricing
            community_price = item.get("communityPrice")
            if community_price and community_price > 0:
                offers.append(GpuOffer(
                    provider=ProviderName.RUNPOD,
                    offer_id=f"{type_id}:COMMUNITY",
                    gpu_type=display_name,
                    gpu_count=1,
                    gpu_ram_gb=item.get("memoryInGb", 0),
                    price_per_hour=community_price,
                    region="COMMUNITY",
                    availability=1 if item.get("communityCloud") else 0,
                ))

        return offers

    def list_volumes(self) -> list[VolumeInfo]:
        """List all network volumes in the account."""
        gql_headers = {"Authorization": f"Bearer {self._api_key}"}
        resp = httpx.post(
            self.GRAPHQL_URL,
            json={"query": "query { myself { networkVolumes { id name size dataCenterId } } }"},
            headers=gql_headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        volumes = resp.json().get("data", {}).get("myself", {}).get("networkVolumes", [])
        return [
            VolumeInfo(
                provider=ProviderName.RUNPOD,
                volume_id=v["id"],
                name=v.get("name", ""),
                size_gb=v.get("size", 0),
                region=v.get("dataCenterId", ""),
                mount_path="/workspace",
            )
            for v in volumes
        ]

    def create_volume(self, name: str, size_gb: int, data_center_id: str) -> VolumeInfo:
        """Create a new network volume."""
        resp = self._client.post(
            "/networkvolumes",
            json={"name": name, "size": size_gb, "dataCenterId": data_center_id},
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"RunPod create_volume failed: {resp.status_code} {resp.text}")
        vol = resp.json()
        return VolumeInfo(
            provider=ProviderName.RUNPOD,
            volume_id=vol["id"],
            name=name,
            size_gb=size_gb,
            region=data_center_id,
            mount_path="/workspace",
        )

    def create_instance(self, config: InstanceConfig) -> InstanceInfo:
        # Register SSH key in RunPod account settings (required for SSH access)
        if config.ssh_public_key:
            self._ensure_ssh_key(config.ssh_public_key)

        # Parse offer_id format: "{gpu_type_id}:{cloud_type}"
        if ":" in config.offer_id:
            gpu_type_id, cloud_type = config.offer_id.rsplit(":", 1)
        else:
            gpu_type_id = config.gpu_type
            cloud_type = "SECURE"

        data: dict = {
            "name": config.name,
            "imageName": config.image,
            "gpuTypeIds": [gpu_type_id],
            "cloudType": cloud_type,
            "gpuCount": config.gpu_count,
            "volumeInGb": config.disk_gb,
            "containerDiskInGb": 20,
            "minVCPUPerGPU": 1,
            "minRAMPerGPU": 1,
            "supportPublicIp": True,
            "ports": ["22/tcp"],
        }

        if config.volume_id:
            data["networkVolumeId"] = config.volume_id

        resp = self._client.post("/pods", json=data)
        if resp.status_code >= 300:
            raise httpx.HTTPStatusError(
                f"RunPod create_instance failed: {resp.status_code} {resp.text}",
                request=resp.request,
                response=resp,
            )
        pod = resp.json()

        return InstanceInfo(
            provider=ProviderName.RUNPOD,
            instance_id=pod["id"],
            name=config.name,
            status=InstanceStatus.STARTING,
            gpu_type=config.gpu_type,
            gpu_count=config.gpu_count,
        )

    def get_instance(self, instance_id: str) -> InstanceInfo:
        resp = self._client.get(f"/pods/{instance_id}")
        resp.raise_for_status()
        pod = resp.json()

        status_map = {
            "RUNNING": InstanceStatus.RUNNING,
            "EXITED": InstanceStatus.STOPPED,
            "CREATED": InstanceStatus.STARTING,
        }
        status = status_map.get(pod.get("desiredStatus", ""), InstanceStatus.PENDING)

        ssh = None
        public_ip = pod.get("publicIp")
        if public_ip:
            # RunPod maps container port 22 to a random host port
            port_mappings = pod.get("portMappings") or {}
            ssh_port = int(port_mappings.get("22", 22))
            ssh = SshConnectionInfo(host=public_ip, port=ssh_port, username="root")

        return InstanceInfo(
            provider=ProviderName.RUNPOD,
            instance_id=instance_id,
            name=pod.get("name", ""),
            status=status,
            gpu_type=pod.get("gpuTypeId", ""),
            ssh=ssh,
        )

    def wait_until_ready(self, instance_id: str, timeout: int = 900) -> InstanceInfo:
        deadline = time.time() + timeout
        delay = 5.0
        last_status = ""
        while time.time() < deadline:
            info = self.get_instance(instance_id)
            # Log status changes so user can see progress
            status_str = f"{info.status.value}"
            if info.ssh:
                status_str += f" ssh={info.ssh.host}:{info.ssh.port}"
            if status_str != last_status:
                from autofoundry.theme import console
                console.print(
                    f"  [af.muted]  polling: {status_str}[/af.muted]"
                )
                last_status = status_str
            if info.status == InstanceStatus.RUNNING and info.ssh:
                return info
            time.sleep(min(delay, deadline - time.time()))
            delay = min(delay * 1.5, 30.0)
        raise TimeoutError(f"RunPod instance {instance_id} not ready within {timeout}s")

    def get_ssh_info(self, instance_id: str) -> SshConnectionInfo:
        info = self.get_instance(instance_id)
        if info.ssh is None:
            raise RuntimeError(f"No SSH info available for RunPod instance {instance_id}")
        return info.ssh

    def stop_instance(self, instance_id: str) -> None:
        """Stop a pod (releases GPU, keeps disk). Cheap storage-only billing."""
        resp = self._client.post(f"/pods/{instance_id}/stop")
        resp.raise_for_status()

    def start_instance(self, instance_id: str) -> InstanceInfo:
        """Restart a stopped pod. Near-instant since disk is preserved."""
        resp = self._client.post(f"/pods/{instance_id}/start")
        resp.raise_for_status()
        return self.get_instance(instance_id)

    def delete_instance(self, instance_id: str) -> None:
        resp = self._client.delete(f"/pods/{instance_id}")
        resp.raise_for_status()
