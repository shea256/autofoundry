"""
PRIME Intellect provider: configuration, formatters, and API client.
"""

import json
import requests
from typing import Dict, Any, Optional, List

# PRIME Intellect profile configurations
PROFILES = {
    "axolotl": {
        # Resource requirements
        "gpu_type": "H100_80GB",
        "gpu_count": 1,
        "socket": "SXM",
        "security": "secure_cloud",
        "disk_size": 100,
        # Optional: store a default image
        "image": "pytorch",
    },
}


def get_preset(profile: str) -> Dict[str, Any]:
    """Get PRIME Intellect configuration for a profile."""
    return PROFILES.get(profile, {}).copy()


def list_profiles() -> list[str]:
    """List all available PRIME Intellect profiles."""
    return list(PROFILES.keys())


def _format_value(value):
    """Format a value for display in pod details."""
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, separators=(",", ":"))
        except Exception:
            return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def format_pod_details(pod: Dict[str, Any]) -> str:
    """Format PRIME Intellect pod details for display."""
    lines = []
    fields = [
        ("id", "id"),
        ("name", "name"),
        ("status", "status"),
        ("gpu type", "gpuType"),
        ("gpu count", "gpuCount"),
        ("socket", "socket"),
        ("image", "image"),
        ("price/hr", "priceHr"),
        ("cloud id", "cloudId"),
        ("data center", "dataCenterId"),
        ("security", "security"),
        ("ssh connection", "sshConnection"),
        ("disk size (GB)", "diskSize"),
        ("vcpus", "vcpus"),
    ]

    label_width = max(len(label) for label, _ in fields) if fields else 0
    for label, key in fields:
        value = _format_value(pod.get(key))
        lines.append(f"  {label.ljust(label_width)} : {value}")

    return "\n".join(lines)


# API Client
class API:
    """Client for interacting with PRIME Intellect REST API"""

    BASE_URL = "https://api.primeintellect.ai/api/v1"

    def __init__(self, api_key: str):
        """Initialize the PRIME Intellect API client."""
        if not api_key:
            raise ValueError("API key is required.")
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None, expect_json: bool = True
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the PRIME Intellect API and return JSON.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: Data to send as JSON body
            params: Query parameters
            expect_json: If False, return success dict instead of parsing JSON
        """
        url = f"{self.BASE_URL}{endpoint}"
        response = requests.request(
            method=method, url=url, headers=self.headers, json=data, params=params
        )
        response.raise_for_status()

        # Some endpoints return empty responses, handle those gracefully
        if not expect_json or not response.text.strip():
            return {"success": True, "status_code": response.status_code}

        return response.json()

    def create_pod(
        self,
        name: str,
        cloud_id: str,
        gpu_type: str,
        provider_type: str,
        gpu_count: int = 1,
        image: str = "ubuntu_22_cuda_12",
        socket: Optional[str] = None,
        security: str = "secure_cloud",
        disk_size: Optional[int] = None,
        vcpus: Optional[int] = None,
        data_center_id: Optional[str] = None,
        country: Optional[str] = None,
        max_price: Optional[float] = None,
        custom_template_id: Optional[str] = None,
        disks: Optional[List[str]] = None,
        team_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new pod on PRIME Intellect.

        Args:
            name: Instance identifier
            cloud_id: Machine configuration ID (from availability check)
            gpu_type: GPU model (e.g., "H100_80GB", "A100_80GB")
            provider_type: Cloud provider type (e.g., "datacrunch", "hyperstack", "runpod")
            gpu_count: Number of GPUs (default: 1)
            image: OS/software environment (default: "ubuntu_22_cuda_12")
            socket: Connection type (e.g., "PCIe", "SXM")
            security: Security classification ("secure_cloud" or "community_cloud")
            disk_size: Storage in GB
            vcpus: vCPU count
            data_center_id: Specific data center location
            country: Region code
            max_price: Price ceiling per hour
            custom_template_id: Custom environment ID (use with image="custom_template")
            disks: Array of disk IDs for attachment
            team_id: Team assignment

        Returns:
            Dictionary containing created pod details
        """
        payload = {
            "pod": {
                "name": name,
                "cloudId": cloud_id,
                "gpuType": gpu_type,
                "gpuCount": gpu_count,
                "image": image,
                "security": security,
            },
            "provider": {
                "type": provider_type,
            },
        }

        if socket:
            payload["pod"]["socket"] = socket
        if disk_size is not None:
            payload["pod"]["diskSize"] = disk_size
        if vcpus is not None:
            payload["pod"]["vcpus"] = vcpus
        if data_center_id:
            payload["pod"]["dataCenterId"] = data_center_id
        if country:
            payload["pod"]["country"] = country
        if max_price is not None:
            payload["pod"]["maxPrice"] = max_price
        if custom_template_id:
            payload["pod"]["customTemplateId"] = custom_template_id
        if disks:
            payload["disks"] = disks
        if team_id:
            payload["team"] = {"teamId": team_id}

        return self._make_request("POST", "/pods/", data=payload)

    def list_pods(self, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        """
        List all pods in your account.

        Args:
            offset: Pagination offset (default: 0)
            limit: Maximum number of results (default: 100)

        Returns:
            Dictionary with total_count, offset, limit, and data array
        """
        params = {"offset": offset, "limit": limit}
        return self._make_request("GET", "/pods/", params=params)

    def get_pod(self, pod_id: str) -> Dict[str, Any]:
        """Get details of a specific pod."""
        return self._make_request("GET", f"/pods/{pod_id}")

    def get_pod_status(self, pod_ids: List[str]) -> Dict[str, Any]:
        """
        Get status of one or more pods.

        Args:
            pod_ids: List of pod IDs to check

        Returns:
            Array of pod status objects
        """
        params = {"pod_ids": pod_ids}
        return self._make_request("GET", "/pods/status/", params=params)

    def delete_pod(self, pod_id: str) -> Dict[str, Any]:
        """Delete a pod."""
        return self._make_request("DELETE", f"/pods/{pod_id}", expect_json=False)

    def check_gpu_availability(
        self,
        regions: Optional[List[str]] = None,
        gpu_count: Optional[int] = None,
        gpu_type: Optional[str] = None,
        socket: Optional[str] = None,
        security: Optional[str] = None,
        data_center_id: Optional[str] = None,
        cloud_id: Optional[str] = None,
        disks: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """
        Check GPU availability across providers.

        Args:
            regions: Geographic locations (e.g., ["united_states", "canada"])
            gpu_count: Desired GPU quantity
            gpu_type: Model identifier (e.g., "H100_80GB", "A100_80GB")
            socket: Socket type ("PCIe" or "SXM")
            security: "secure_cloud" or "community_cloud"
            data_center_id: Specific datacenter filter
            cloud_id: Provider's cloud identifier
            disks: Disk IDs for filtering
            page: Page number (default: 1)
            page_size: Results per page (default: 100, max: 100)

        Returns:
            Dictionary with items array and totalCount
        """
        params = {"page": page, "page_size": page_size}

        if regions:
            params["regions"] = regions
        if gpu_count is not None:
            params["gpu_count"] = gpu_count
        if gpu_type:
            params["gpu_type"] = gpu_type
        if socket:
            params["socket"] = socket
        if security:
            params["security"] = security
        if data_center_id:
            params["data_center_id"] = data_center_id
        if cloud_id:
            params["cloud_id"] = cloud_id
        if disks:
            params["disks"] = disks

        return self._make_request("GET", "/availability/gpus", params=params)

    def check_disk_availability(
        self,
        regions: Optional[List[str]] = None,
        data_center_id: Optional[str] = None,
        cloud_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """
        Check disk availability across providers.

        Args:
            regions: Geographic locations
            data_center_id: Specific datacenter filter
            cloud_id: Provider's cloud identifier
            page: Page number (default: 1)
            page_size: Results per page (default: 100, max: 100)

        Returns:
            Dictionary with items array and totalCount
        """
        params = {"page": page, "page_size": page_size}

        if regions:
            params["regions"] = regions
        if data_center_id:
            params["data_center_id"] = data_center_id
        if cloud_id:
            params["cloud_id"] = cloud_id

        return self._make_request("GET", "/availability/disks", params=params)
