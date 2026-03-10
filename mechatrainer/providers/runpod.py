"""
RunPod provider: configuration, formatters, and API client.
"""

import json
import requests
from typing import Dict, Any, Optional, List, Union

# RunPod profile configurations
PROFILES = {
    "axolotl": {
        # RunPod-specific: Docker image and start command
        "image": "axolotlai/axolotl-base:main-base-py3.11-cu128-2.7.1",
        "start_cmd": "/bin/bash -lc 'eval \"$(/root/miniconda3/bin/conda shell.bash hook)\"; conda activate py3.11; mkdir -p /workspace && cd /workspace; nvidia-smi || true; axolotl --help || true; sleep infinity'",
        # GPU and resource requirements
        "cloud_type": "SECURE",
        "gpu_count": 1,
        "gpu_type": "NVIDIA L40S",
        "container_disk_in_gb": 20,
        "min_vcpu_per_gpu": 2,
        "min_ram_per_gpu": 8,
    },
}


def get_preset(profile: str) -> Dict[str, Any]:
    """Get RunPod configuration for a profile."""
    return PROFILES.get(profile, {}).copy()


def list_profiles() -> list[str]:
    """List all available RunPod profiles."""
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
    """Format RunPod pod details for display."""
    lines = []
    fields = [
        ("name", "name"),
        ("id", "id"),
        ("consumer user id", "consumerUserId"),
        ("container disk (GB)", "containerDiskInGb"),
        ("volume (GB)", "volumeInGb"),
        ("created at", "createdAt"),
        ("last started at", "lastStartedAt"),
        ("desired status", "desiredStatus"),
        ("last status change", "lastStatusChange"),
        ("template id", "templateId"),
        ("image name", "imageName"),
        ("machine id", "machineId"),
        ("ports", "ports"),
        ("public ip", "publicIp"),
        ("volume mount path", "volumeMountPath"),
    ]
    
    label_width = max(len(label) for label, _ in fields) if fields else 0
    for label, key in fields:
        value = _format_value(pod.get(key))
        lines.append(f"  {label.ljust(label_width)} : {value}")

    return "\n".join(lines)


# API Client
class API:
    """Client for interacting with RunPod.io REST API"""

    BASE_URL = "https://rest.runpod.io/v1"

    def __init__(self, api_key: str):
        """Initialize the RunPod API client."""
        if not api_key:
            raise ValueError("API key is required.")
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": self.api_key,
        }

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make an HTTP request to the RunPod API and return JSON."""
        url = f"{self.BASE_URL}{endpoint}"
        response = requests.request(method=method, url=url, headers=self.headers, json=data)
        response.raise_for_status()
        return response.json()

    def create_pod(
        self,
        name: str,
        image_name: str,
        gpu_type_ids: List[str],
        cloud_type: str = "SECURE",
        network_volume_id: Optional[str] = None,
        data_center_id: Optional[str] = None,
        country_code: Optional[str] = None,
        gpu_count: int = 1,
        volume_in_gb: int = 0,
        container_disk_in_gb: int = 10,
        min_vcpu_per_gpu: int = 1,
        min_ram_per_gpu: int = 1,
        docker_args: Optional[str] = None,
        ports: Optional[str] = None,
        volume_mount_path: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        start_jupyter: bool = False,
        start_ssh: bool = False,
        support_public_ip: bool = True,
        template_id: Optional[str] = None,
        docker_start_command: Optional[Union[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        """Create a new pod with configuration options."""
        payload = {
            "name": name,
            "imageName": image_name,
            "gpuTypeIds": gpu_type_ids,
            "cloudType": cloud_type,
            "gpuCount": gpu_count,
            "volumeInGb": volume_in_gb,
            "containerDiskInGb": container_disk_in_gb,
            "minVCPUPerGPU": min_vcpu_per_gpu,
            "minRAMPerGPU": min_ram_per_gpu,
            "supportPublicIp": support_public_ip,
        }

        if network_volume_id:
            payload["networkVolumeId"] = network_volume_id
        if data_center_id:
            payload["dataCenterId"] = data_center_id
        if country_code:
            payload["countryCode"] = country_code
        if docker_args:
            payload["dockerArgs"] = docker_args
        if ports:
            payload["ports"] = ports
        if volume_mount_path:
            payload["volumeMountPath"] = volume_mount_path
        if env:
            payload["env"] = env
        if template_id:
            payload["templateId"] = template_id
        if docker_start_command is not None:
            # API requires an array of strings; normalize accordingly
            if isinstance(docker_start_command, list):
                normalized_list = [str(part) for part in docker_start_command]
            else:
                normalized_list = [str(docker_start_command)]
            payload["dockerStartCmd"] = normalized_list

        print(json.dumps(payload))
        return self._make_request("POST", "/pods", data=payload)

    def list_pods(self) -> Dict[str, Any]:
        """List all pods in your account."""
        return self._make_request("GET", "/pods")

    def get_pod(self, pod_id: str) -> Dict[str, Any]:
        """Get details of a specific pod."""
        return self._make_request("GET", f"/pods/{pod_id}")

    def update_pod(self, pod_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a pod using PATCH method."""
        return self._make_request("PATCH", f"/pods/{pod_id}", data=data)

    def delete_pod(self, pod_id: str) -> Dict[str, Any]:
        """Delete a pod."""
        return self._make_request("DELETE", f"/pods/{pod_id}")

    def update_pod_post(self, pod_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a pod using POST method."""
        return self._make_request("POST", f"/pods/{pod_id}", data=data)

    def start_pod(self, pod_id: str) -> Dict[str, Any]:
        """Start or resume a pod."""
        return self._make_request("POST", f"/pods/{pod_id}/start")

    def stop_pod(self, pod_id: str) -> Dict[str, Any]:
        """Stop a pod."""
        return self._make_request("POST", f"/pods/{pod_id}/stop")

    def reset_pod(self, pod_id: str) -> Dict[str, Any]:
        """Reset a pod."""
        return self._make_request("POST", f"/pods/{pod_id}/reset")

    def restart_pod(self, pod_id: str) -> Dict[str, Any]:
        """Restart a pod."""
        return self._make_request("POST", f"/pods/{pod_id}/restart")

