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

    def __init__(self, api_key: str, min_bandwidth_mbps: float = 5000.0) -> None:
        if not api_key:
            raise ValueError("Vast.ai API key is required")
        self._api_key = api_key
        self._min_bandwidth_mbps = min_bandwidth_mbps
        self._ssh_key_synced = False
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def _ensure_ssh_key(self, public_key: str) -> None:
        """Register SSH public key in Vast.ai account via API."""
        if self._ssh_key_synced or not public_key:
            return

        # Check existing SSH keys
        resp = self._client.get("/ssh/")
        if resp.status_code == 200:
            existing_keys = resp.json() if isinstance(resp.json(), list) else []
            for key_entry in existing_keys:
                if isinstance(key_entry, dict) and public_key.strip() in key_entry.get("public_key", ""):
                    self._ssh_key_synced = True
                    return

        # Register new key
        resp = self._client.post(
            "/ssh/",
            json={"ssh_key": public_key.strip()},
        )
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Failed to register SSH key with Vast.ai ({resp.status_code}): {resp.text}"
            )
        self._ssh_key_synced = True

    def validate_key(self) -> bool:
        try:
            resp = self._client.get("/instances", params={"api_key": self._api_key})
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def _find_gpu_variants(self, gpu_type: str) -> list[str]:
        """Find all Vast.ai GPU names matching a search term (e.g., 'H100' -> ['H100 NVL', 'H100 PCIE', 'H100 SXM'])."""
        # Query a small set of cheap offers to discover GPU names, then separately
        # query expensive ones (H100s won't appear in cheapest results)
        all_names: set[str] = set()
        for min_price in [0.0, 1.0]:
            query: dict = {
                "rentable": {"eq": True},
                "type": "on-demand",
                "order": [["dph_total", "asc"]],
                "limit": 500,
                "allocated_storage": 5.0,
            }
            if min_price > 0:
                query["dph_total"] = {"gte": min_price}
            resp = self._client.post(
                "/bundles/",
                json=query,
                params={"api_key": self._api_key},
            )
            if resp.status_code != 200:
                continue
            for item in resp.json().get("offers", []):
                name = item.get("gpu_name", "")
                if name:
                    all_names.add(name)

        return [n for n in all_names if gpu_type.upper() in n.upper()]

    def list_gpu_offers(
        self, gpu_type: str | None = None, *, vram_min: float | None = None,
    ) -> list[GpuOffer]:
        # Vast.ai CLI uses POST /bundles/ with query as JSON body
        query: dict = {
            "rentable": {"eq": True},
            "type": "on-demand",
            "order": [["dph_total", "asc"]],
            "limit": 100,
            "allocated_storage": 5.0,
        }
        if self._min_bandwidth_mbps > 0:
            query["inet_down"] = {"gte": self._min_bandwidth_mbps}

        # Server-side VRAM filter (in MB) for tier-based queries
        if vram_min is not None:
            query["gpu_ram"] = {"gte": vram_min * 1024}

        # Server-side GPU name filter using the "in" operator
        if gpu_type:
            variants = self._find_gpu_variants(gpu_type)
            if not variants:
                return []
            query["gpu_name"] = {"in": variants}

        resp = self._client.post(
            "/bundles/",
            json=query,
            params={"api_key": self._api_key},
        )
        resp.raise_for_status()
        data = resp.json()

        # Response uses "offers" key
        items = data.get("offers", data.get("bundles", data)) if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = []

        offers = []
        for item in items:
            if not isinstance(item, dict):
                continue

            gpu_name = item.get("gpu_name", "Unknown")

            # Client-side GPU type filter: match if user's query is a substring
            if gpu_type and gpu_type.upper() not in gpu_name.upper():
                continue

            # Skip non-rentable offers (belt-and-suspenders with server filter)
            if not item.get("rentable", True) or item.get("rented", False):
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
                inet_down_mbps=item.get("inet_down", 0) or 0,
                availability=1,
            ))
        return offers

    def create_instance(self, config: InstanceConfig) -> InstanceInfo:
        offer_id = config.offer_id
        if not offer_id:
            raise ValueError("Vast.ai requires an offer_id on InstanceConfig")

        # Register SSH key at account level (Vast.ai uses account keys, not per-instance env vars)
        if config.ssh_public_key:
            self._ensure_ssh_key(config.ssh_public_key)

        payload: dict = {
            "client_id": "me",
            "image": config.image,
            "disk": float(config.disk_gb),
            "label": config.name,
            "runtype": "ssh",
        }

        resp = self._client.put(
            f"/asks/{offer_id}/",
            json=payload,
            params={"api_key": self._api_key},
        )
        if resp.status_code >= 300:
            raise httpx.HTTPStatusError(
                f"Vast.ai create_instance failed ({resp.status_code}): {resp.text}",
                request=resp.request,
                response=resp,
            )
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
        ssh_host = instance.get("ssh_host")
        ssh_port = instance.get("ssh_port")
        if ssh_host and ssh_port:
            ssh = SshConnectionInfo(host=ssh_host, port=int(ssh_port), username="root")

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

    def stop_instance(self, instance_id: str) -> None:
        """Stop an instance (releases GPU, keeps disk)."""
        resp = self._client.put(
            f"/instances/{instance_id}/",
            json={"state": "stopped"},
            params={"api_key": self._api_key},
        )
        resp.raise_for_status()

    def start_instance(self, instance_id: str) -> InstanceInfo:
        """Restart a stopped instance."""
        resp = self._client.put(
            f"/instances/{instance_id}/",
            json={"state": "running"},
            params={"api_key": self._api_key},
        )
        resp.raise_for_status()
        return self.get_instance(instance_id)

    def delete_instance(self, instance_id: str) -> None:
        resp = self._client.delete(
            f"/instances/{instance_id}",
            params={"api_key": self._api_key},
        )
        resp.raise_for_status()
