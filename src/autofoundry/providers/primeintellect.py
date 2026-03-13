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
            follow_redirects=True,
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
                    "vcpu_default": str((item.get("vcpu") or {}).get("defaultCount") or ""),
                    "memory_default": str((item.get("memory") or {}).get("defaultCount") or ""),
                    "disk_default": str((item.get("disk") or {}).get("defaultCount") or ""),
                    "country": str(item.get("country") or ""),
                    "is_spot": str(item.get("isSpot") or "false"),
                    "images": ",".join(item.get("images") or []),
                },
            ))

        # Filter out sub-providers with known SSH key propagation and
        # provisioning reliability issues
        _BLOCKED_PROVIDERS = {"massedcompute"}
        offers = [
            o for o in offers
            if o.metadata.get("provider_type", "") not in _BLOCKED_PROVIDERS
        ]

        return offers

    def _ensure_ssh_key(self, ssh_public_key: str) -> str:
        """Register SSH public key with PI and set as primary.

        PI only propagates the primary SSH key to sub-providers.
        Returns the key ID.
        """
        if not ssh_public_key:
            return ""

        import logging
        logger = logging.getLogger(__name__)

        # Check existing keys (PI API requires trailing slash)
        resp = self._client.get("/ssh_keys/")
        key_id = ""
        if resp.status_code == 200:
            existing = resp.json().get("data", [])
            for key in existing:
                if key.get("publicKey", "").strip() == ssh_public_key.strip():
                    key_id = key.get("id", "")
                    if key.get("isPrimary"):
                        return key_id  # Already registered and primary
                    break

        # Register new key if not found
        if not key_id:
            import hashlib
            key_hash = hashlib.sha256(ssh_public_key.encode()).hexdigest()[:8]
            resp = self._client.post(
                "/ssh_keys/",
                json={"name": f"autofoundry-{key_hash}", "publicKey": ssh_public_key},
            )
            if resp.status_code >= 300:
                raise RuntimeError(
                    f"Failed to register SSH key with PRIME Intellect "
                    f"({resp.status_code}): {resp.text}"
                )
            key_id = resp.json().get("id", "")
            logger.info("Registered SSH key with PRIME Intellect")

        # Set as primary so sub-providers propagate it
        if key_id:
            resp = self._client.patch(
                f"/ssh_keys/{key_id}/",
                json={"isPrimary": True},
            )
            if resp.status_code < 300:
                logger.info("Set SSH key as primary on PRIME Intellect")

        return key_id

    def create_instance(self, config: InstanceConfig) -> InstanceInfo:
        # Ensure SSH key is registered before creating instance
        ssh_key_id = self._ensure_ssh_key(config.ssh_public_key)

        # PI requires nested {pod: {...}, provider: {...}} format
        meta = config.metadata
        # vcpus and memory are required by the PI API (lowercase field names)
        vcpu = int(meta.get("vcpu_default") or 0)
        memory = int(meta.get("memory_default") or 0)
        disk = config.disk_gb or int(meta.get("disk_default") or 200)

        # Select an image that is supported by this offer's provider
        available_images = [i for i in meta.get("images", "").split(",") if i]
        # Prefer PyTorch images, then CUDA images, then fall back to ubuntu
        IMAGE_PRIORITY = [
            "cuda_12_4_pytorch_2_4", "cuda_12_4_pytorch_2_5",
            "cuda_12_4_pytorch_2_6", "cuda_12_6_pytorch_2_7",
            "cuda_12_1_pytorch_2_4", "cuda_12_1_pytorch_2_3",
            "cuda_12_1_pytorch_2_2", "ubuntu_22_cuda_12",
        ]
        image = "ubuntu_22_cuda_12"  # default fallback
        if available_images:
            for preferred in IMAGE_PRIORITY:
                if preferred in available_images:
                    image = preferred
                    break
            else:
                image = available_images[0]

        payload: dict = {
            "pod": {
                "name": config.name,
                "cloudId": config.offer_id,
                "gpuType": config.gpu_type,
                "gpuCount": config.gpu_count,
                "image": image,
                "security": meta.get("security", "secure_cloud"),
                "disk_size": disk,
            },
            "provider": {
                "type": meta.get("provider_type", ""),
            },
        }
        if vcpu:
            payload["pod"]["vcpus"] = vcpu
        if memory:
            payload["pod"]["memory"] = memory

        data_center = meta.get("data_center_id")
        if not data_center:
            raise ValueError(
                f"No data_center_id for {config.gpu_type} on PRIME Intellect. "
                "This may indicate the offer metadata is incomplete."
            )
        payload["pod"]["dataCenterId"] = data_center

        if meta.get("socket"):
            payload["pod"]["socket"] = meta["socket"]

        resp = self._client.post("/pods/", json=payload, timeout=120.0)
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

        import logging
        logger = logging.getLogger(__name__)
        logger.debug("PI get_instance raw response: %s", pod)

        raw_status = pod.get("status", "")
        status_map = {
            "running": InstanceStatus.RUNNING,
            "active": InstanceStatus.RUNNING,
            "stopped": InstanceStatus.STOPPED,
            "pending": InstanceStatus.STARTING,
            "provisioning": InstanceStatus.STARTING,
            "starting": InstanceStatus.STARTING,
            "created": InstanceStatus.STARTING,
            "failed": InstanceStatus.ERROR,
            "error": InstanceStatus.ERROR,
            "terminated": InstanceStatus.DELETED,
        }
        status = status_map.get(raw_status.lower(), InstanceStatus.PENDING)

        # Parse SSH connection info — PI returns sshConnection as a string
        # like "ssh user@host -p port" or as a dict, or ip as a plain string
        ssh = None
        ssh_conn = (
            pod.get("sshConnection")
            or pod.get("ssh_connection")
            or pod.get("sshTerminal")
            or pod.get("ssh_terminal")
            or pod.get("ssh")
        )

        if isinstance(ssh_conn, dict) and ssh_conn.get("host"):
            ssh = SshConnectionInfo(
                host=ssh_conn["host"],
                port=ssh_conn.get("port", 22),
                username=ssh_conn.get("username", "root"),
            )
        elif isinstance(ssh_conn, str) and ssh_conn:
            import re
            host_match = re.search(r"@([\w.\-]+)", ssh_conn)
            port_match = re.search(r"-p\s+(\d+)", ssh_conn)
            user_match = re.search(r"ssh\s+(\w+)@", ssh_conn)
            if host_match:
                ssh = SshConnectionInfo(
                    host=host_match.group(1),
                    port=int(port_match.group(1)) if port_match else 22,
                    username=user_match.group(1) if user_match else "root",
                )

        # Fallback: if sshConnection is null but ip is available, use ip directly
        if ssh is None and pod.get("ip"):
            ssh = SshConnectionInfo(
                host=pod["ip"],
                port=22,
                username="root",
            )

        return InstanceInfo(
            provider=ProviderName.PRIMEINTELLECT,
            instance_id=instance_id,
            name=pod.get("name", ""),
            status=status,
            gpu_type=pod.get("gpuName", pod.get("gpu_type", "")),
            gpu_count=pod.get("gpuCount", pod.get("gpu_count", 1)),
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
