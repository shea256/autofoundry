"""Tests for Lambda Labs volume (filesystem) operations."""

from unittest.mock import MagicMock

import pytest

from autofoundry.models import InstanceConfig, ProviderName
from autofoundry.providers.lambdalabs import LambdaLabsProvider


@pytest.fixture
def provider() -> LambdaLabsProvider:
    return LambdaLabsProvider(api_key="test-key")


class TestListVolumes:
    def test_parses_filesystem_response(self, provider: LambdaLabsProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "fs-abc",
                    "name": "my-storage",
                    "bytes_used": 107374182400,  # 100 GB
                    "region": {"name": "us-east-1"},
                },
            ]
        }

        provider._client = MagicMock()
        provider._client.get.return_value = mock_resp

        volumes = provider.list_volumes()

        assert len(volumes) == 1
        assert volumes[0].volume_id == "fs-abc"
        assert volumes[0].name == "my-storage"
        assert volumes[0].size_gb == 100
        assert volumes[0].region == "us-east-1"
        assert volumes[0].mount_path == "/lambda/nfs/persistent-storage"
        assert volumes[0].provider == ProviderName.LAMBDALABS

    def test_empty_filesystems(self, provider: LambdaLabsProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}

        provider._client = MagicMock()
        provider._client.get.return_value = mock_resp

        assert provider.list_volumes() == []


class TestCreateVolume:
    def test_creates_filesystem(self, provider: LambdaLabsProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": "fs-new-123"}}

        provider._client = MagicMock()
        provider._client.post.return_value = mock_resp

        vol = provider.create_volume("test-fs", "us-west-1")

        assert vol.volume_id == "fs-new-123"
        assert vol.name == "test-fs"
        assert vol.region == "us-west-1"
        assert vol.mount_path == "/lambda/nfs/persistent-storage"

        provider._client.post.assert_called_once_with(
            "/file-systems",
            json={"name": "test-fs", "region": "us-west-1"},
        )

    def test_create_volume_failure(self, provider: LambdaLabsProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"

        provider._client = MagicMock()
        provider._client.post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="create filesystem failed"):
            provider.create_volume("bad-fs", "us-east-1")


class TestCreateInstanceWithVolume:
    def test_passes_file_system_names(self, provider: LambdaLabsProvider) -> None:
        # Mock SSH key registration
        provider._ssh_key_name = "autofoundry"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"instance_ids": ["i-123"]}}

        provider._client = MagicMock()
        provider._client.post.return_value = mock_resp

        config = InstanceConfig(
            name="test-instance",
            gpu_type="H100",
            gpu_count=1,
            offer_id="gpu_1x_h100_sxm5",
            volume_id="my-storage",
            metadata={"region_name": "us-east-1"},
        )
        provider.create_instance(config)

        call_args = provider._client.post.call_args
        payload = call_args[1]["json"]
        assert payload["file_system_names"] == ["my-storage"]

    def test_no_volume_omits_field(self, provider: LambdaLabsProvider) -> None:
        provider._ssh_key_name = "autofoundry"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"instance_ids": ["i-456"]}}

        provider._client = MagicMock()
        provider._client.post.return_value = mock_resp

        config = InstanceConfig(
            name="test-instance",
            gpu_type="H100",
            gpu_count=1,
            offer_id="gpu_1x_h100_sxm5",
            metadata={"region_name": "us-east-1"},
        )
        provider.create_instance(config)

        call_args = provider._client.post.call_args
        payload = call_args[1]["json"]
        assert "file_system_names" not in payload
