"""PRIME Intellect GPU cloud provider."""

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


class PrimeIntellectProvider:
    """PRIME Intellect API client implementing the CloudProvider protocol."""

    name = "primeintellect"
    BASE_URL = "https://api.primeintellect.ai/api/v1"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("PRIME Intellect API key is required")
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def validate_key(self) -> bool:
        try:
            resp = self._client.get("/pods/", params={"offset": 0, "limit": 1})
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def _find_gpu_type_ids(self, gpu_type: str) -> list[str]:
        """Discover PI gpu_type IDs matching a search term (e.g. 'H100' -> ['H100_80GB']).

        PI's API requires exact gpu_type IDs and returns 422 for partial matches,
        so we scan all pages to discover valid IDs first.
        """
        all_types: set[str] = set()
        page = 1
        while True:
            resp = self._client.get(
                "/availability/gpus", params={"page": page, "page_size": 100}
            )
            if resp.status_code != 200:
                break
            items = resp.json().get("items", [])
            if not items:
                break
            for item in items:
                gt = item.get("gpuType", "")
                if gt:
                    all_types.add(gt)
            page += 1

        return [t for t in all_types if gpu_type.upper() in t.upper()]

    def list_gpu_offers(self, gpu_type: str | None = None) -> list[GpuOffer]:
        # Find matching GPU type IDs for server-side filtering
        gpu_type_ids: list[str] = []
        if gpu_type:
            gpu_type_ids = self._find_gpu_type_ids(gpu_type)
            if not gpu_type_ids:
                return []

        # Fetch offers — use server-side gpu_type filter when possible
        all_items: list[dict] = []
        targets = gpu_type_ids if gpu_type_ids else [None]

        for type_id in targets:
            page = 1
            while True:
                params: dict = {"page": page, "page_size": 100}
                if type_id:
                    params["gpu_type"] = type_id
                resp = self._client.get("/availability/gpus", params=params)
                if resp.status_code != 200:
                    break
                items = resp.json().get("items", [])
                if not items:
                    break
                all_items.extend(items)
                page += 1

        offers = []
        for item in all_items:
            if not isinstance(item, dict):
                continue

            item_gpu_type = item.get("gpuType", item.get("gpu_type", ""))

            # Client-side filter as belt-and-suspenders
            if gpu_type and gpu_type.upper() not in item_gpu_type.upper():
                continue

            # Price is nested under "prices.onDemand"
            prices = item.get("prices", {})
            price = prices.get("onDemand", 0.0) if isinstance(prices, dict) else 0.0
            if not price:
                price = item.get("price", 0.0)
            if not price or price <= 0:
                continue

            # stockStatus: treat missing/empty as available (PI may omit this field)
            stock = item.get("stockStatus", "available").lower()
            avail = 0 if stock in ("out_of_stock", "unavailable") else 1

            offers.append(GpuOffer(
                provider=ProviderName.PRIMEINTELLECT,
                offer_id=item.get("cloudId", str(item.get("id", ""))),
                gpu_type=item_gpu_type,
                gpu_count=item.get("gpuCount") or item.get("gpu_count") or 1,
                gpu_ram_gb=item.get("gpuMemory") or item.get("gpu_ram_gb") or 0,
                price_per_hour=price,
                region=item.get("region", item.get("data_center_id")),
                availability=avail,
                metadata={
                    "provider_type": str(item.get("provider") or ""),
                    "socket": str(item.get("socket") or ""),
                    "security": str(item.get("security") or "secure_cloud"),
                    "data_center_id": str(item.get("dataCenter") or ""),
                },
            ))
        return offers

    def create_instance(self, config: InstanceConfig) -> InstanceInfo:
        # PI requires nested {pod: {...}, provider: {...}} format
        # with camelCase fields and cloudId from availability response
        meta = config.metadata
        payload: dict = {
            "pod": {
                "name": config.name,
                "cloudId": config.offer_id,
                "gpuType": config.gpu_type,
                "gpuCount": config.gpu_count,
                "image": "ubuntu_22_cuda_12",
                "security": meta.get("security", "secure_cloud"),
            },
            "provider": {
                "type": meta.get("provider_type", ""),
            },
        }
        if meta.get("socket"):
            payload["pod"]["socket"] = meta["socket"]
        if config.disk_gb:
            payload["pod"]["diskSize"] = config.disk_gb

        resp = self._client.post("/pods/", json=payload)
        if resp.status_code >= 300:
            raise httpx.HTTPStatusError(
                f"PI create_instance failed: {resp.status_code} {resp.text}",
                request=resp.request,
                response=resp,
            )
        pod = resp.json()

        return InstanceInfo(
            provider=ProviderName.PRIMEINTELLECT,
            instance_id=pod.get("id", ""),
            name=config.name,
            status=InstanceStatus.STARTING,
            gpu_type=config.gpu_type,
            gpu_count=config.gpu_count,
            price_per_hour=pod.get("priceHr", 0.0),
        )

    def get_instance(self, instance_id: str) -> InstanceInfo:
        resp = self._client.get(f"/pods/{instance_id}")
        resp.raise_for_status()
        pod = resp.json()

        status_map = {
            "running": InstanceStatus.RUNNING,
            "stopped": InstanceStatus.STOPPED,
            "pending": InstanceStatus.STARTING,
        }
        status = status_map.get(pod.get("status", ""), InstanceStatus.PENDING)

        ssh = None
        ssh_conn = pod.get("sshConnection", {})
        if ssh_conn and ssh_conn.get("host"):
            ssh = SshConnectionInfo(
                host=ssh_conn["host"],
                port=ssh_conn.get("port", 22),
                username=ssh_conn.get("username", "root"),
            )

        return InstanceInfo(
            provider=ProviderName.PRIMEINTELLECT,
            instance_id=instance_id,
            name=pod.get("name", ""),
            status=status,
            gpu_type=pod.get("gpu_type", ""),
            gpu_count=pod.get("gpu_count", 1),
            price_per_hour=pod.get("priceHr", 0.0),
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
        raise TimeoutError(
            f"PRIME Intellect instance {instance_id} not ready within {timeout}s"
        )

    def get_ssh_info(self, instance_id: str) -> SshConnectionInfo:
        info = self.get_instance(instance_id)
        if info.ssh is None:
            raise RuntimeError(
                f"No SSH info available for PRIME Intellect instance {instance_id}"
            )
        return info.ssh

    def delete_instance(self, instance_id: str) -> None:
        resp = self._client.delete(f"/pods/{instance_id}")
        resp.raise_for_status()
