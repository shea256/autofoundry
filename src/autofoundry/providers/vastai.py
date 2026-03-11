"""Vast.ai GPU cloud provider."""

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
)


class VastAIProvider:
    """Vast.ai API client implementing the CloudProvider protocol."""

    name = "vastai"
    BASE_URL = "https://console.vast.ai/api/v0"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Vast.ai API key is required")
        self._api_key = api_key
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def validate_key(self) -> bool:
        try:
            resp = self._client.get("/instances", params={"api_key": self._api_key})
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def list_gpu_offers(self, gpu_type: str | None = None) -> list[GpuOffer]:
        # Query without gpu_name filter — filter client-side for substring matching
        params: dict = {"api_key": self._api_key}

        resp = self._client.get("/bundles/", params=params)
        resp.raise_for_status()
        data = resp.json()

        # Response uses "bundles" key
        items = data.get("bundles", data.get("offers", data)) if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = []

        offers = []
        for item in items:
            if not isinstance(item, dict):
                continue

            gpu_name = item.get("gpu_name", "Unknown")

            # Client-side filter: match if user's query is a substring
            if gpu_type and gpu_type.upper() not in gpu_name.upper():
                continue

            price = item.get("dph_total", 0)
            if price <= 0:
                continue

            gpu_ram = item.get("gpu_ram", 0)
            offers.append(GpuOffer(
                provider=ProviderName.VASTAI,
                offer_id=str(item.get("id", "")),
                gpu_type=gpu_name,
                gpu_count=item.get("num_gpus", 1),
                gpu_ram_gb=gpu_ram / 1024 if gpu_ram > 100 else gpu_ram,
                price_per_hour=price,
                region=item.get("geolocation", ""),
                availability=1,
            ))
        return offers

    def create_instance(self, config: InstanceConfig) -> InstanceInfo:
        offer_id = config.offer_id
        if not offer_id:
            raise ValueError("Vast.ai requires an offer_id on InstanceConfig")

        payload = {
            "client_id": "me",
            "image": config.image,
            "disk": config.disk_gb,
            "label": config.name,
        }

        resp = self._client.put(f"/asks/{offer_id}/", json=payload)
        resp.raise_for_status()
        data = resp.json()
        instance_id = str(data.get("new_contract", data.get("id", "")))

        return InstanceInfo(
            provider=ProviderName.VASTAI,
            instance_id=instance_id,
            name=config.name,
            status=InstanceStatus.STARTING,
            gpu_type=config.gpu_type,
            gpu_count=config.gpu_count,
        )

    def get_instance(self, instance_id: str) -> InstanceInfo:
        resp = self._client.get(
            f"/instances/{instance_id}",
            params={"api_key": self._api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        instance = data.get("instances", data) if isinstance(data, dict) else data

        status_map = {
            "running": InstanceStatus.RUNNING,
            "stopped": InstanceStatus.STOPPED,
            "loading": InstanceStatus.STARTING,
        }
        status = status_map.get(
            instance.get("actual_status", ""), InstanceStatus.PENDING
        )

        ssh = None
        public_ip = instance.get("public_ipaddr")
        ssh_port = instance.get("ssh_port")
        if public_ip and ssh_port:
            ssh = SshConnectionInfo(host=public_ip, port=ssh_port, username="root")

        return InstanceInfo(
            provider=ProviderName.VASTAI,
            instance_id=instance_id,
            name=instance.get("label", ""),
            status=status,
            gpu_type=instance.get("gpu_name", ""),
            ssh=ssh,
        )

    def wait_until_ready(self, instance_id: str, timeout: int = 300) -> InstanceInfo:
        deadline = time.time() + timeout
        delay = 5.0
        while time.time() < deadline:
            info = self.get_instance(instance_id)
            if info.status == InstanceStatus.RUNNING and info.ssh:
                return info
            time.sleep(min(delay, deadline - time.time()))
            delay = min(delay * 1.5, 30.0)
        raise TimeoutError(f"Vast.ai instance {instance_id} not ready within {timeout}s")

    def get_ssh_info(self, instance_id: str) -> SshConnectionInfo:
        info = self.get_instance(instance_id)
        if info.ssh is None:
            raise RuntimeError(f"No SSH info available for Vast.ai instance {instance_id}")
        return info.ssh

    def delete_instance(self, instance_id: str) -> None:
        resp = self._client.delete(
            f"/instances/{instance_id}",
            params={"api_key": self._api_key},
        )
        resp.raise_for_status()
