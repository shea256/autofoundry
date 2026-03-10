"""
Vast.ai provider: configuration, formatters, and API client.
"""

import json
import requests
from typing import Dict, Any, Optional

# Vast.ai profile configurations
PROFILES = {
    "axolotl": {
        # Vast.ai-specific: template ID (if using templates instead of image/command)
        "template_id": None,
        # Resource requirements
        "disk_gb": 20,
        # GPU search criteria for finding offers
        "gpu_search": {
            "gpu_name": "L40S",
            "min_gpu_ram": 24,
        },
        # Optional: store a default offer_id if you have a preferred one
        # "offer_id": "12345",
    },
}


def get_preset(profile: str) -> Dict[str, Any]:
    """Get Vast.ai configuration for a profile."""
    return PROFILES.get(profile, {}).copy()


def list_profiles() -> list[str]:
    """List all available Vast.ai profiles."""
    return list(PROFILES.keys())


def _format_value(value):
    """Format a value for display in instance details."""
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


def format_instance_details(instance: Dict[str, Any]) -> str:
    """Format Vast.ai instance details for display."""
    lines = []
    fields = [
        ("id", "id"),
        ("name", "label"),
        ("image", "image"),
        ("command", "command"),
        ("disk (GB)", "disk"),
        ("status", "status"),
        ("public ip", "public_ipaddr"),
        ("gpu", "gpu_name"),
        ("gpu ram (GB)", "gpu_ram"),
        ("created", "created"),
    ]
    
    label_width = max(len(label) for label, _ in fields) if fields else 0
    for label, key in fields:
        value = _format_value(instance.get(key))
        lines.append(f"  {label.ljust(label_width)} : {value}")

    return "\n".join(lines)


# API Client
class API:
    """Client for interacting with Vast.ai REST API"""

    BASE_URL = "https://console.vast.ai/api/v0"

    def __init__(self, api_key: str):
        """Initialize the Vast.ai API client."""
        if not api_key:
            raise ValueError("API key is required.")
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, use_params: bool = False, expect_json: bool = True
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Vast.ai API and return JSON.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: Data to send (as JSON body or query params)
            use_params: If True, send data as query parameters (for GET requests)
            expect_json: If False, return success dict instead of parsing JSON (for empty responses)
        """
        url = f"{self.BASE_URL}{endpoint}"

        if use_params and data:
            response = requests.request(method=method, url=url, headers=self.headers, params=data)
        else:
            response = requests.request(method=method, url=url, headers=self.headers, json=data)

        response.raise_for_status()

        # Some endpoints return empty responses, handle those gracefully
        if not expect_json or not response.text.strip():
            return {"success": True, "status_code": response.status_code}

        return response.json()

    def create_instance(
        self,
        offer_id: str,
        image: str,
        command: str,
        disk_gb: int = 10,
        env: Optional[Dict[str, str]] = None,
        ports: Optional[str] = None,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new instance (pod) on Vast.ai.

        Args:
            offer_id: The ID of the GPU offer to use
            image: Docker image to use
            command: Command to run in the container
            disk_gb: Disk size in GB (default: 10)
            env: Optional environment variables dictionary
            ports: Optional port mappings
            label: Optional label for the instance

        Returns:
            Dictionary containing created instance details
        """
        # Vast.ai uses PUT method with query parameters for creating instances
        payload = {
            "client_id": "me",  # Use "me" as client_id
            "image": image,
            "args": command.split() if isinstance(command, str) else command,
            "disk": disk_gb,
        }

        if env:
            payload["env"] = env
        if ports:
            payload["onstart"] = ports
        if label:
            payload["label"] = label

        # Use PUT with the offer_id in the URL
        return self._make_request("PUT", f"/asks/{offer_id}/", data=payload)

    def list_instances(self) -> Dict[str, Any]:
        """List all instances (pods) in your account."""
        payload = {"api_key": self.api_key}
        return self._make_request("GET", "/instances", data=payload)

    def get_instance(self, instance_id: str) -> Dict[str, Any]:
        """
        Get details of a specific instance.

        Note: Vast.ai API returns the instance wrapped in an "instances" key.
        This method unwraps it for consistency with other methods.
        """
        payload = {"api_key": self.api_key}
        response = self._make_request("GET", f"/instances/{instance_id}", data=payload)

        # Vast.ai wraps the instance data in an "instances" key, unwrap it
        if isinstance(response, dict) and "instances" in response:
            return response["instances"]

        return response

    def update_instance(self, instance_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an instance using PATCH method.
        
        Args:
            instance_id: The ID of the instance to update
            data: Dictionary containing fields to update
            
        Returns:
            Dictionary containing updated instance details
        """
        payload = {"api_key": self.api_key, **data}
        return self._make_request("PATCH", f"/instances/{instance_id}", data=payload)

    def delete_instance(self, instance_id: str) -> Dict[str, Any]:
        """Delete an instance."""
        payload = {"api_key": self.api_key}
        return self._make_request("DELETE", f"/instances/{instance_id}", data=payload)

    def start_instance(self, instance_id: str) -> Dict[str, Any]:
        """Start or resume an instance."""
        # Vast.ai uses PUT method for starting instances
        return self._make_request("PUT", f"/instances/{instance_id}/", data={"state": "running"}, expect_json=False)

    def stop_instance(self, instance_id: str) -> Dict[str, Any]:
        """Stop an instance."""
        # Vast.ai uses PUT method for stopping instances
        return self._make_request("PUT", f"/instances/{instance_id}/", data={"state": "stopped"}, expect_json=False)

    def restart_instance(self, instance_id: str) -> Dict[str, Any]:
        """Restart an instance."""
        # Vast.ai restart is done by stopping then starting
        self.stop_instance(instance_id)
        import time
        time.sleep(2)  # Brief pause between stop and start
        return self.start_instance(instance_id)

    def search_offers(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Search for available GPU offers on Vast.ai.

        Note: This endpoint may not be available in the Vast.ai REST API.
        Consider using the Vast.ai CLI tool for searching offers instead.

        Args:
            filters: Dictionary of filter parameters (e.g., {"gpu_name": "RTX 4090", "min_price": 0.5})

        Returns:
            Dictionary containing list of matching offers

        Raises:
            NotImplementedError: If the endpoint is not available
        """
        # The /offers endpoint may not be available in the REST API
        # Try using /bundles endpoint as an alternative
        payload = {
            "api_key": self.api_key,
        }

        if filters:
            payload.update(filters)

        try:
            # Try the bundles endpoint which may be used for searching
            return self._make_request("GET", "/bundles", data=payload, use_params=True)
        except Exception:
            # If bundles doesn't work, raise a clear error
            raise NotImplementedError(
                "Search offers endpoint is not available via Vast.ai REST API. "
                "Please use the Vast.ai CLI tool or web interface to search for offers."
            )

