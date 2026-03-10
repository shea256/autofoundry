"""Unit tests for RunPod API read-only operations."""

import pytest
from unittest.mock import Mock, patch
from providers.runpod import API


class TestRunPodAPI:
    """Test suite for RunPod API client read-only operations."""

    @pytest.fixture
    def api_client(self):
        """Create a RunPod API client for testing."""
        return API(api_key="test_api_key_123")

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
        assert client.headers["x-api-key"] == "test_key"

    def test_api_initialization_no_key(self):
        """Test API client initialization fails without API key."""
        with pytest.raises(ValueError, match="API key is required"):
            API(api_key="")

    @patch('providers.runpod.requests.request')
    def test_list_pods_success(self, mock_request, api_client, mock_response):
        """Test successfully listing all pods."""
        # Mock response data
        expected_data = [
            {
                "id": "pod123",
                "name": "test-pod-1",
                "desiredStatus": "RUNNING",
                "imageName": "python:3.9",
                "machineId": "machine123",
                "gpuCount": 1,
            },
            {
                "id": "pod456",
                "name": "test-pod-2",
                "desiredStatus": "STOPPED",
                "imageName": "pytorch/pytorch:latest",
                "machineId": "machine456",
                "gpuCount": 2,
            }
        ]

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        # Call the method
        result = api_client.list_pods()

        # Assertions
        assert result == expected_data
        mock_request.assert_called_once_with(
            method="GET",
            url="https://rest.runpod.io/v1/pods",
            headers=api_client.headers,
            json=None
        )

    @patch('providers.runpod.requests.request')
    def test_list_pods_empty(self, mock_request, api_client, mock_response):
        """Test listing pods when no pods exist."""
        mock_response.json.return_value = []
        mock_request.return_value = mock_response

        result = api_client.list_pods()

        assert result == []
        assert isinstance(result, list)

    @patch('providers.runpod.requests.request')
    def test_get_pod_success(self, mock_request, api_client, mock_response):
        """Test successfully getting a specific pod."""
        pod_id = "pod123"
        expected_data = {
            "id": pod_id,
            "name": "test-pod",
            "desiredStatus": "RUNNING",
            "imageName": "python:3.9",
            "machineId": "machine123",
            "gpuCount": 1,
            "containerDiskInGb": 10,
            "volumeInGb": 50,
            "createdAt": "2024-01-01T00:00:00Z",
            "ports": "8888/http",
            "publicIp": "192.168.1.1",
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        # Call the method
        result = api_client.get_pod(pod_id)

        # Assertions
        assert result == expected_data
        assert result["id"] == pod_id
        assert result["name"] == "test-pod"
        mock_request.assert_called_once_with(
            method="GET",
            url=f"https://rest.runpod.io/v1/pods/{pod_id}",
            headers=api_client.headers,
            json=None
        )

    @patch('providers.runpod.requests.request')
    def test_get_pod_not_found(self, mock_request, api_client):
        """Test getting a pod that doesn't exist."""
        from requests.exceptions import HTTPError

        pod_id = "nonexistent_pod"
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_request.return_value = mock_response

        with pytest.raises(HTTPError):
            api_client.get_pod(pod_id)

    @patch('providers.runpod.requests.request')
    def test_list_pods_api_error(self, mock_request, api_client):
        """Test handling API errors when listing pods."""
        from requests.exceptions import HTTPError

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("500 Internal Server Error")
        mock_request.return_value = mock_response

        with pytest.raises(HTTPError):
            api_client.list_pods()

    @patch('providers.runpod.requests.request')
    def test_list_pods_with_complex_data(self, mock_request, api_client, mock_response):
        """Test listing pods with complex nested data structures."""
        expected_data = [
            {
                "id": "pod789",
                "name": "complex-pod",
                "desiredStatus": "RUNNING",
                "imageName": "custom/image:v1",
                "machineId": "machine789",
                "gpuCount": 4,
                "ports": "8888/http,22/tcp",
                "env": {
                    "API_KEY": "secret",
                    "DEBUG": "true"
                },
                "volumeMountPath": "/workspace",
                "containerDiskInGb": 100,
            }
        ]

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.list_pods()

        assert result == expected_data
        assert result[0]["env"]["API_KEY"] == "secret"
        assert result[0]["gpuCount"] == 4

    @patch('providers.runpod.requests.request')
    def test_get_pod_with_all_fields(self, mock_request, api_client, mock_response):
        """Test getting a pod with all possible fields populated."""
        pod_id = "fullpod123"
        expected_data = {
            "id": pod_id,
            "name": "full-featured-pod",
            "consumerUserId": "user123",
            "containerDiskInGb": 20,
            "volumeInGb": 100,
            "createdAt": "2024-01-01T00:00:00Z",
            "lastStartedAt": "2024-01-01T01:00:00Z",
            "desiredStatus": "RUNNING",
            "lastStatusChange": "2024-01-01T01:05:00Z",
            "templateId": "template123",
            "imageName": "pytorch/pytorch:latest",
            "machineId": "machine999",
            "ports": "8888/http,22/tcp,6006/http",
            "publicIp": "203.0.113.42",
            "volumeMountPath": "/workspace",
            "gpuCount": 2,
            "cloudType": "SECURE",
        }

        mock_response.json.return_value = expected_data
        mock_request.return_value = mock_response

        result = api_client.get_pod(pod_id)

        assert result == expected_data
        assert result["id"] == pod_id
        assert result["gpuCount"] == 2
        assert result["cloudType"] == "SECURE"
        assert result["volumeMountPath"] == "/workspace"

    def test_api_headers_format(self, api_client):
        """Test that API headers are correctly formatted."""
        headers = api_client.headers

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")
        assert "x-api-key" in headers
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
