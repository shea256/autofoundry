"""Unit tests for Vast.ai API read-only operations."""

import pytest
from unittest.mock import Mock, patch
from providers.vastai import API


class TestVastAIAPI:
    """Test suite for Vast.ai API client read-only operations."""

    @pytest.fixture
    def api_client(self):
        """Create a Vast.ai API client for testing."""
        return API(api_key="test_api_key_xyz")

    @pytest.fixture
    def mock_response(self):
        """Create a mock response object."""
        mock = Mock()
        mock.raise_for_status = Mock()
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

    @patch('providers.vastai.requests.request')
    def test_list_instances_success(self, mock_request, api_client, mock_response):
        """Test successfully listing all instances."""
        # Mock response data
        expected_data = {
            "instances": [
                {
                    "id": 12345,
                    "label": "test-instance-1",
                    "image": "pytorch/pytorch:latest",
                    "status": "running",
                    "gpu_name": "RTX 4090",
                    "gpu_ram": 24,
                    "disk": 50,
                    "public_ipaddr": "203.0.113.1",
                },
                {
                    "id": 67890,
                    "label": "test-instance-2",
                    "image": "tensorflow/tensorflow:latest",
                    "status": "stopped",
                    "gpu_name": "L40S",
                    "gpu_ram": 48,
                    "disk": 100,
                    "public_ipaddr": "203.0.113.2",
                }
            ]
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        # Call the method
        result = api_client.list_instances()

        # Assertions
        assert result == expected_data
        assert "instances" in result
        assert len(result["instances"]) == 2
        mock_request.assert_called_once_with(
            method="GET",
            url="https://console.vast.ai/api/v0/instances",
            headers=api_client.headers,
            json={"api_key": api_client.api_key}
        )

    @patch('providers.vastai.requests.request')
    def test_list_instances_empty(self, mock_request, api_client, mock_response):
        """Test listing instances when no instances exist."""
        mock_response.json.return_value = {"instances": []}
        mock_request.return_value = mock_response

        result = api_client.list_instances()

        assert result["instances"] == []
        assert isinstance(result["instances"], list)

    @patch('providers.vastai.requests.request')
    def test_list_instances_as_list(self, mock_request, api_client, mock_response):
        """Test listing instances when API returns a list instead of dict."""
        expected_data = [
            {
                "id": 11111,
                "label": "instance-1",
                "status": "running",
            }
        ]

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.list_instances()

        assert result == expected_data
        assert isinstance(result, list)

    @patch('providers.vastai.requests.request')
    def test_get_instance_success(self, mock_request, api_client, mock_response):
        """Test successfully getting a specific instance."""
        instance_id = "12345"
        instance_data = {
            "id": 12345,
            "label": "test-instance",
            "image": "pytorch/pytorch:latest",
            "command": "python train.py",
            "status": "running",
            "gpu_name": "RTX 4090",
            "gpu_ram": 24,
            "disk": 50,
            "public_ipaddr": "203.0.113.10",
            "created": "2024-01-01T00:00:00Z",
        }

        # Vast.ai wraps the instance in an "instances" key
        api_response = {"instances": instance_data}
        mock_response.json.return_value = api_response
        mock_request.return_value = mock_response

        # Call the method
        result = api_client.get_instance(instance_id)

        # Assertions - should return unwrapped instance data
        assert result == instance_data
        assert result["id"] == 12345
        assert result["label"] == "test-instance"
        mock_request.assert_called_once_with(
            method="GET",
            url=f"https://console.vast.ai/api/v0/instances/{instance_id}",
            headers=api_client.headers,
            json={"api_key": api_client.api_key}
        )

    @patch('providers.vastai.requests.request')
    def test_get_instance_not_found(self, mock_request, api_client):
        """Test getting an instance that doesn't exist."""
        from requests.exceptions import HTTPError

        instance_id = "99999"
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_request.return_value = mock_response

        with pytest.raises(HTTPError):
            api_client.get_instance(instance_id)

    @patch('providers.vastai.requests.request')
    def test_search_offers_success(self, mock_request, api_client, mock_response):
        """Test successfully searching for GPU offers (if endpoint is available)."""
        expected_data = {
            "bundles": [
                {
                    "id": 1001,
                    "gpu_name": "RTX 4090",
                    "gpu_ram": 24,
                    "price": 0.45,
                    "cpu_cores": 16,
                    "ram": 64,
                    "disk_space": 500,
                    "datacenter": "US-East",
                    "reliability": 0.99,
                },
                {
                    "id": 1002,
                    "gpu_name": "L40S",
                    "gpu_ram": 48,
                    "price": 0.89,
                    "cpu_cores": 32,
                    "ram": 128,
                    "disk_space": 1000,
                    "datacenter": "EU-West",
                    "reliability": 0.98,
                }
            ]
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        # Call the method
        result = api_client.search_offers()

        # Assertions
        assert result == expected_data
        assert "bundles" in result
        assert len(result["bundles"]) == 2
        mock_request.assert_called_once_with(
            method="GET",
            url="https://console.vast.ai/api/v0/bundles",
            headers=api_client.headers,
            params={"api_key": api_client.api_key}
        )

    @patch('providers.vastai.requests.request')
    def test_search_offers_with_filters(self, mock_request, api_client, mock_response):
        """Test searching for GPU offers with filters."""
        filters = {
            "gpu_name": "RTX 4090",
            "min_price": 0.3,
            "max_price": 0.6,
            "min_gpu_ram": 24,
        }

        expected_data = {
            "bundles": [
                {
                    "id": 1001,
                    "gpu_name": "RTX 4090",
                    "gpu_ram": 24,
                    "price": 0.45,
                }
            ]
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        # Call the method
        result = api_client.search_offers(filters=filters)

        # Assertions
        assert result == expected_data
        mock_request.assert_called_once_with(
            method="GET",
            url="https://console.vast.ai/api/v0/bundles",
            headers=api_client.headers,
            params={
                "api_key": api_client.api_key,
                **filters
            }
        )

    @patch('providers.vastai.requests.request')
    def test_search_offers_empty_results(self, mock_request, api_client, mock_response):
        """Test searching for offers with no matches."""
        mock_response.json.return_value = {"bundles": []}
        mock_request.return_value = mock_response

        result = api_client.search_offers(filters={"gpu_name": "NonexistentGPU"})

        assert result["bundles"] == []
        assert isinstance(result["bundles"], list)

    @patch('providers.vastai.requests.request')
    def test_list_instances_api_error(self, mock_request, api_client):
        """Test handling API errors when listing instances."""
        from requests.exceptions import HTTPError

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("500 Internal Server Error")
        mock_request.return_value = mock_response

        with pytest.raises(HTTPError):
            api_client.list_instances()

    @patch('providers.vastai.requests.request')
    def test_search_offers_api_error(self, mock_request, api_client):
        """Test handling API errors when searching offers."""
        from requests.exceptions import HTTPError

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("401 Unauthorized")
        mock_request.return_value = mock_response

        # Should raise NotImplementedError after catching the HTTPError
        with pytest.raises(NotImplementedError, match="Search offers endpoint is not available"):
            api_client.search_offers()

    @patch('providers.vastai.requests.request')
    def test_get_instance_with_all_fields(self, mock_request, api_client, mock_response):
        """Test getting an instance with all possible fields populated."""
        instance_id = "54321"
        instance_data = {
            "id": 54321,
            "label": "full-featured-instance",
            "image": "custom/image:v2",
            "command": "bash -c 'python train.py --epochs 100'",
            "status": "running",
            "gpu_name": "A100",
            "gpu_ram": 80,
            "disk": 200,
            "public_ipaddr": "203.0.113.99",
            "private_ipaddr": "10.0.0.5",
            "created": "2024-01-01T00:00:00Z",
            "started": "2024-01-01T00:05:00Z",
            "ended": None,
            "ssh_port": 22001,
            "direct_port_start": 30000,
            "direct_port_end": 30100,
        }

        # Vast.ai wraps the instance in an "instances" key
        api_response = {"instances": instance_data}
        mock_response.json.return_value = api_response
        mock_request.return_value = mock_response

        result = api_client.get_instance(instance_id)

        assert result == instance_data
        assert result["id"] == 54321
        assert result["gpu_name"] == "A100"
        assert result["gpu_ram"] == 80

    @patch('providers.vastai.requests.request')
    def test_search_offers_with_complex_filters(self, mock_request, api_client, mock_response):
        """Test searching offers with multiple complex filters."""
        filters = {
            "gpu_name": ["RTX 4090", "L40S", "A100"],
            "min_gpu_ram": 24,
            "max_price": 1.0,
            "cpu_cores": {"min": 16},
            "datacenter": "US-East",
            "reliability": {"min": 0.95},
        }

        expected_data = {
            "bundles": [
                {
                    "id": 2001,
                    "gpu_name": "A100",
                    "price": 0.95,
                }
            ]
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.search_offers(filters=filters)

        assert result == expected_data
        assert len(result["bundles"]) == 1

    def test_api_headers_format(self, api_client):
        """Test that API headers are correctly formatted."""
        headers = api_client.headers

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    @patch('providers.vastai.requests.request')
    def test_list_instances_with_complex_data(self, mock_request, api_client, mock_response):
        """Test listing instances with complex nested data structures."""
        expected_data = {
            "instances": [
                {
                    "id": 99999,
                    "label": "complex-instance",
                    "image": "custom/complex:latest",
                    "status": "running",
                    "gpu_name": "H100",
                    "gpu_ram": 80,
                    "disk": 500,
                    "env": {
                        "WANDB_API_KEY": "secret",
                        "CUDA_VISIBLE_DEVICES": "0,1,2,3"
                    },
                    "ports": {
                        "8888": 8888,
                        "6006": 6006,
                    },
                }
            ]
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.list_instances()

        assert result == expected_data
        assert result["instances"][0]["env"]["WANDB_API_KEY"] == "secret"
        assert result["instances"][0]["gpu_ram"] == 80
