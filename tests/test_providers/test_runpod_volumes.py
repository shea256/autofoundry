"""Tests for RunPod volume operations."""

from unittest.mock import MagicMock, patch

import pytest

from autofoundry.models import InstanceConfig, ProviderName
from autofoundry.providers.runpod import RunPodProvider


@pytest.fixture
def provider() -> RunPodProvider:
    return RunPodProvider(api_key="test-key")


class TestListVolumes:
    def test_parses_graphql_response(self, provider: RunPodProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "myself": {
                    "networkVolumes": [
                        {
                            "id": "vol-abc",
                            "name": "my-workspace",
                            "size": 100,
                            "dataCenterId": "US-TX-3",
                        },
                        {
                            "id": "vol-def",
                            "name": "datasets",
                            "size": 500,
                            "dataCenterId": "EU-RO-1",
                        },
                    ]
                }
            }
        }

        with patch("httpx.post", return_value=mock_resp):
            volumes = provider.list_volumes()

        assert len(volumes) == 2
        assert volumes[0].volume_id == "vol-abc"
        assert volumes[0].name == "my-workspace"
        assert volumes[0].size_gb == 100
        assert volumes[0].region == "US-TX-3"
        assert volumes[0].mount_path == "/workspace"
        assert volumes[0].provider == ProviderName.RUNPOD

    def test_empty_volumes(self, provider: RunPodProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"myself": {"networkVolumes": []}}
        }

        with patch("httpx.post", return_value=mock_resp):
            volumes = provider.list_volumes()

        assert volumes == []


class TestCreateVolume:
    def test_creates_volume(self, provider: RunPodProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "vol-new-123"}

        provider._client = MagicMock()
        provider._client.post.return_value = mock_resp

        vol = provider.create_volume("test-vol", 200, "US-TX-3")

        assert vol.volume_id == "vol-new-123"
        assert vol.name == "test-vol"
        assert vol.size_gb == 200
        assert vol.region == "US-TX-3"
        assert vol.mount_path == "/workspace"

        provider._client.post.assert_called_once_with(
            "/networkvolumes",
            json={"name": "test-vol", "size": 200, "dataCenterId": "US-TX-3"},
        )

    def test_create_volume_failure(self, provider: RunPodProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"

        provider._client = MagicMock()
        provider._client.post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="create_volume failed"):
            provider.create_volume("bad-vol", 100, "XX-YY-1")


class TestCreateInstanceWithVolume:
    def test_passes_network_volume_id(self, provider: RunPodProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": "pod-123"}

        provider._client = MagicMock()
        provider._client.post.return_value = mock_resp

        config = InstanceConfig(
            name="test-pod",
            gpu_type="H100",
            gpu_count=1,
            offer_id="NVIDIA H100:SECURE",
            volume_id="vol-abc",
        )
        provider.create_instance(config)

        call_args = provider._client.post.call_args
        payload = call_args[1]["json"]
        assert payload["networkVolumeId"] == "vol-abc"

    def test_no_volume_id_omits_field(self, provider: RunPodProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": "pod-456"}

        provider._client = MagicMock()
        provider._client.post.return_value = mock_resp

        config = InstanceConfig(
            name="test-pod",
            gpu_type="H100",
            gpu_count=1,
            offer_id="NVIDIA H100:SECURE",
        )
        provider.create_instance(config)

        call_args = provider._client.post.call_args
        payload = call_args[1]["json"]
        assert "networkVolumeId" not in payload
