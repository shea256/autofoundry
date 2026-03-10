"""Unit tests for PRIME Intellect API read-only operations."""

import pytest
from unittest.mock import Mock, patch
from providers.primeintellect import API


class TestPrimeIntellectAPI:
    """Test suite for PRIME Intellect API client read-only operations."""

    @pytest.fixture
    def api_client(self):
        """Create a PRIME Intellect API client for testing."""
        return API(api_key="test_api_key_xyz")

    @pytest.fixture
    def mock_response(self):
        """Create a mock response object."""
        mock = Mock()
        mock.raise_for_status = Mock()
        mock.text = "{}"
        return mock

    def test_api_initialization(self):
        """Test API client initialization with valid API key."""
        client = API(api_key="test_key")
        assert client.api_key == "test_key"
        assert "Bearer test_key" in client.headers["Authorization"]

    def test_api_initialization_no_key(self):
        """Test API client initialization fails without API key."""
        with pytest.raises(ValueError, match="API key is required"):
            API(api_key="")

    @patch('providers.primeintellect.requests.request')
    def test_list_pods_success(self, mock_request, api_client, mock_response):
        """Test successfully listing all pods."""
        expected_data = {
            "total_count": 2,
            "offset": 0,
            "limit": 100,
            "data": [
                {
                    "id": "pod-12345",
                    "name": "test-pod-1",
                    "status": "running",
                    "gpuType": "H100_80GB",
                    "gpuCount": 1,
                    "socket": "SXM",
                    "image": "pytorch",
                    "priceHr": 2.50,
                    "cloudId": "cloud-abc",
                    "security": "secure_cloud",
                },
                {
                    "id": "pod-67890",
                    "name": "test-pod-2",
                    "status": "stopped",
                    "gpuType": "A100_80GB",
                    "gpuCount": 2,
                    "socket": "PCIe",
                    "image": "tensorflow",
                    "priceHr": 3.00,
                    "cloudId": "cloud-def",
                    "security": "community_cloud",
                }
            ]
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.list_pods()

        assert result == expected_data
        assert "data" in result
        assert len(result["data"]) == 2
        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.primeintellect.ai/api/v1/pods/",
            headers=api_client.headers,
            json=None,
            params={"offset": 0, "limit": 100}
        )

    @patch('providers.primeintellect.requests.request')
    def test_list_pods_empty(self, mock_request, api_client, mock_response):
        """Test listing pods when no pods exist."""
        mock_response.json.return_value = {"total_count": 0, "offset": 0, "limit": 100, "data": []}
        mock_request.return_value = mock_response

        result = api_client.list_pods()

        assert result["data"] == []
        assert result["total_count"] == 0

    @patch('providers.primeintellect.requests.request')
    def test_list_pods_with_pagination(self, mock_request, api_client, mock_response):
        """Test listing pods with pagination parameters."""
        expected_data = {"total_count": 50, "offset": 10, "limit": 20, "data": []}
        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.list_pods(offset=10, limit=20)

        assert result == expected_data
        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.primeintellect.ai/api/v1/pods/",
            headers=api_client.headers,
            json=None,
            params={"offset": 10, "limit": 20}
        )

    @patch('providers.primeintellect.requests.request')
    def test_get_pod_success(self, mock_request, api_client, mock_response):
        """Test successfully getting a specific pod."""
        pod_id = "pod-12345"
        pod_data = {
            "id": "pod-12345",
            "name": "test-pod",
            "status": "running",
            "gpuType": "H100_80GB",
            "gpuCount": 1,
            "socket": "SXM",
            "image": "pytorch",
            "priceHr": 2.50,
            "cloudId": "cloud-abc",
            "dataCenterId": "dc-001",
            "security": "secure_cloud",
            "sshConnection": "ssh user@192.168.1.1 -p 22001",
            "diskSize": 100,
            "vcpus": 16,
        }

        mock_response.json.return_value = pod_data
        mock_request.return_value = mock_response

        result = api_client.get_pod(pod_id)

        assert result == pod_data
        assert result["id"] == "pod-12345"
        assert result["name"] == "test-pod"
        mock_request.assert_called_once_with(
            method="GET",
            url=f"https://api.primeintellect.ai/api/v1/pods/{pod_id}",
            headers=api_client.headers,
            json=None,
            params=None
        )

    @patch('providers.primeintellect.requests.request')
    def test_get_pod_not_found(self, mock_request, api_client):
        """Test getting a pod that doesn't exist."""
        from requests.exceptions import HTTPError

        pod_id = "pod-99999"
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_request.return_value = mock_response

        with pytest.raises(HTTPError):
            api_client.get_pod(pod_id)

    @patch('providers.primeintellect.requests.request')
    def test_get_pod_status_success(self, mock_request, api_client, mock_response):
        """Test successfully getting status of multiple pods."""
        pod_ids = ["pod-12345", "pod-67890"]
        status_data = [
            {
                "podId": "pod-12345",
                "status": "running",
                "ip": "192.168.1.1",
                "sshConnection": "ssh user@192.168.1.1 -p 22001",
                "costPerHr": 2.50,
            },
            {
                "podId": "pod-67890",
                "status": "stopped",
                "ip": None,
                "sshConnection": None,
                "costPerHr": 0,
            }
        ]

        mock_response.json.return_value = status_data
        mock_request.return_value = mock_response

        result = api_client.get_pod_status(pod_ids)

        assert result == status_data
        assert len(result) == 2
        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.primeintellect.ai/api/v1/pods/status/",
            headers=api_client.headers,
            json=None,
            params={"pod_ids": pod_ids}
        )

    @patch('providers.primeintellect.requests.request')
    def test_check_gpu_availability_success(self, mock_request, api_client, mock_response):
        """Test successfully checking GPU availability."""
        expected_data = {
            "items": [
                {
                    "cloudId": "cloud-abc",
                    "gpuType": "H100_80GB",
                    "socket": "SXM",
                    "provider": "hyperstack",
                    "region": "united_states",
                    "dataCenter": "us-east-1",
                    "country": "US",
                    "gpuCount": 8,
                    "gpuMemory": 80,
                    "stockStatus": "available",
                    "security": "secure_cloud",
                    "prices": {
                        "onDemand": 2.50,
                        "currency": "USD"
                    },
                    "images": ["pytorch", "tensorflow", "jax"]
                },
                {
                    "cloudId": "cloud-def",
                    "gpuType": "A100_80GB",
                    "socket": "PCIe",
                    "provider": "lambda",
                    "region": "canada",
                    "dataCenter": "ca-central-1",
                    "country": "CA",
                    "gpuCount": 4,
                    "gpuMemory": 80,
                    "stockStatus": "available",
                    "security": "secure_cloud",
                    "prices": {
                        "onDemand": 1.80,
                        "currency": "USD"
                    },
                    "images": ["pytorch", "tensorflow"]
                }
            ],
            "totalCount": 2
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.check_gpu_availability()

        assert result == expected_data
        assert "items" in result
        assert len(result["items"]) == 2
        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.primeintellect.ai/api/v1/availability/gpus",
            headers=api_client.headers,
            json=None,
            params={"page": 1, "page_size": 100}
        )

    @patch('providers.primeintellect.requests.request')
    def test_check_gpu_availability_with_filters(self, mock_request, api_client, mock_response):
        """Test checking GPU availability with filters."""
        expected_data = {
            "items": [
                {
                    "cloudId": "cloud-abc",
                    "gpuType": "H100_80GB",
                    "gpuCount": 2,
                    "security": "secure_cloud",
                }
            ],
            "totalCount": 1
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.check_gpu_availability(
            regions=["united_states"],
            gpu_type="H100_80GB",
            gpu_count=2,
            security="secure_cloud",
            socket="SXM"
        )

        assert result == expected_data
        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.primeintellect.ai/api/v1/availability/gpus",
            headers=api_client.headers,
            json=None,
            params={
                "page": 1,
                "page_size": 100,
                "regions": ["united_states"],
                "gpu_type": "H100_80GB",
                "gpu_count": 2,
                "security": "secure_cloud",
                "socket": "SXM"
            }
        )

    @patch('providers.primeintellect.requests.request')
    def test_check_gpu_availability_empty(self, mock_request, api_client, mock_response):
        """Test checking GPU availability with no matches."""
        mock_response.json.return_value = {"items": [], "totalCount": 0}
        mock_request.return_value = mock_response

        result = api_client.check_gpu_availability(gpu_type="NonexistentGPU")

        assert result["items"] == []
        assert result["totalCount"] == 0

    @patch('providers.primeintellect.requests.request')
    def test_check_disk_availability_success(self, mock_request, api_client, mock_response):
        """Test successfully checking disk availability."""
        expected_data = {
            "items": [
                {
                    "cloudId": "cloud-abc",
                    "provider": "hyperstack",
                    "dataCenter": "us-east-1",
                    "country": "US",
                    "region": "united_states",
                    "spec": {
                        "minCount": 10,
                        "maxCount": 1000,
                        "defaultCount": 100,
                        "pricePerUnit": 0.10,
                        "step": 10
                    },
                    "stockStatus": "available",
                    "security": "secure_cloud",
                    "isMultinode": False
                }
            ],
            "totalCount": 1
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.check_disk_availability()

        assert result == expected_data
        assert "items" in result
        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.primeintellect.ai/api/v1/availability/disks",
            headers=api_client.headers,
            json=None,
            params={"page": 1, "page_size": 100}
        )

    @patch('providers.primeintellect.requests.request')
    def test_check_disk_availability_with_filters(self, mock_request, api_client, mock_response):
        """Test checking disk availability with filters."""
        mock_response.json.return_value = {"items": [], "totalCount": 0}
        mock_request.return_value = mock_response

        result = api_client.check_disk_availability(
            regions=["united_states", "canada"],
            data_center_id="dc-001"
        )

        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.primeintellect.ai/api/v1/availability/disks",
            headers=api_client.headers,
            json=None,
            params={
                "page": 1,
                "page_size": 100,
                "regions": ["united_states", "canada"],
                "data_center_id": "dc-001"
            }
        )

    @patch('providers.primeintellect.requests.request')
    def test_list_pods_api_error(self, mock_request, api_client):
        """Test handling API errors when listing pods."""
        from requests.exceptions import HTTPError

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("500 Internal Server Error")
        mock_request.return_value = mock_response

        with pytest.raises(HTTPError):
            api_client.list_pods()

    @patch('providers.primeintellect.requests.request')
    def test_check_gpu_availability_api_error(self, mock_request, api_client):
        """Test handling API errors when checking availability."""
        from requests.exceptions import HTTPError

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("401 Unauthorized")
        mock_request.return_value = mock_response

        with pytest.raises(HTTPError):
            api_client.check_gpu_availability()

    def test_api_headers_format(self, api_client):
        """Test that API headers are correctly formatted."""
        headers = api_client.headers

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    @patch('providers.primeintellect.requests.request')
    def test_get_pod_with_all_fields(self, mock_request, api_client, mock_response):
        """Test getting a pod with all possible fields populated."""
        pod_id = "pod-54321"
        pod_data = {
            "id": "pod-54321",
            "name": "full-featured-pod",
            "status": "running",
            "gpuType": "H100_80GB",
            "gpuCount": 8,
            "socket": "SXM",
            "image": "pytorch",
            "priceHr": 20.00,
            "cloudId": "cloud-premium",
            "dataCenterId": "dc-001",
            "country": "US",
            "security": "secure_cloud",
            "diskSize": 500,
            "vcpus": 64,
            "sshConnection": "ssh user@192.168.1.100 -p 22001",
            "resources": {
                "cpu": 64,
                "memory": 256,
                "disk": 500
            },
            "attachedResources": [
                {"diskId": "disk-001", "mountPath": "/data"}
            ]
        }

        mock_response.json.return_value = pod_data
        mock_request.return_value = mock_response

        result = api_client.get_pod(pod_id)

        assert result == pod_data
        assert result["gpuCount"] == 8
        assert result["gpuType"] == "H100_80GB"

    @patch('providers.primeintellect.requests.request')
    def test_list_pods_with_complex_data(self, mock_request, api_client, mock_response):
        """Test listing pods with complex nested data structures."""
        expected_data = {
            "total_count": 1,
            "offset": 0,
            "limit": 100,
            "data": [
                {
                    "id": "pod-99999",
                    "name": "complex-pod",
                    "status": "running",
                    "gpuType": "H100_80GB",
                    "gpuCount": 4,
                    "priceHr": 10.00,
                    "resources": {
                        "cpu": 32,
                        "memory": 128,
                        "disk": 200
                    },
                    "attachedResources": [
                        {"diskId": "disk-001", "mountPath": "/data"},
                        {"diskId": "disk-002", "mountPath": "/models"}
                    ]
                }
            ]
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.list_pods()

        assert result == expected_data
        assert result["data"][0]["resources"]["cpu"] == 32
        assert len(result["data"][0]["attachedResources"]) == 2
