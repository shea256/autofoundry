"""Tests for the provisioner module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from autofoundry.models import (
    GpuOffer,
    InstanceInfo,
    InstanceStatus,
    ProviderName,
    ProvisioningPlan,
    SshConnectionInfo,
)
from autofoundry.provisioner import _read_ssh_public_key


class TestReadSshPublicKey:
    def test_reads_pub_key_file(self, tmp_path: Path) -> None:
        key_path = tmp_path / "id_rsa"
        pub_path = tmp_path / "id_rsa.pub"
        key_path.write_text("private key")
        pub_path.write_text("ssh-rsa AAAA... user@host\n")

        result = _read_ssh_public_key(str(key_path))
        assert result == "ssh-rsa AAAA... user@host"

    def test_returns_empty_when_no_pub_key(self, tmp_path: Path) -> None:
        key_path = tmp_path / "id_rsa"
        key_path.write_text("private key")

        result = _read_ssh_public_key(str(key_path))
        assert result == ""


class TestProvisionWithVolume:
    def _make_mock_provider(self, instance_id: str = "pod-123"):
        mock = MagicMock()
        info = InstanceInfo(
            provider=ProviderName.RUNPOD,
            instance_id=instance_id,
            name="test",
            status=InstanceStatus.RUNNING,
            gpu_type="H100",
            ssh=SshConnectionInfo(host="1.2.3.4", port=22222),
        )
        mock.create_instance.return_value = info
        mock.wait_until_ready.return_value = info
        return mock

    def test_volume_id_passed_to_instance_config(self, tmp_path: Path) -> None:
        from autofoundry.provisioner import provision_instances

        offer = GpuOffer(
            provider=ProviderName.RUNPOD,
            offer_id="H100:SECURE",
            gpu_type="H100",
            gpu_count=1,
            gpu_ram_gb=80,
            price_per_hour=2.50,
            availability=1,
        )
        plan = ProvisioningPlan(offers=[(offer, 1)], total_experiments=1)

        mock_config = MagicMock()
        mock_config.api_keys = {ProviderName.RUNPOD: "test-key"}
        mock_config.ssh_key_path = str(tmp_path / "id_rsa")
        (tmp_path / "id_rsa.pub").write_text("ssh-rsa AAAA test")

        mock_provider = self._make_mock_provider()
        mock_store = MagicMock()

        with patch("autofoundry.provisioner.get_provider", return_value=mock_provider):
            provision_instances(
                mock_config, plan, "op-1", mock_store,
                volume_id="vol-abc",
            )

        # Check the InstanceConfig passed to create_instance
        call_args = mock_provider.create_instance.call_args
        config = call_args[0][0]
        assert config.volume_id == "vol-abc"

    def test_no_volume_id_defaults_empty(self, tmp_path: Path) -> None:
        from autofoundry.provisioner import provision_instances

        offer = GpuOffer(
            provider=ProviderName.RUNPOD,
            offer_id="H100:SECURE",
            gpu_type="H100",
            gpu_count=1,
            gpu_ram_gb=80,
            price_per_hour=2.50,
            availability=1,
        )
        plan = ProvisioningPlan(offers=[(offer, 1)], total_experiments=1)

        mock_config = MagicMock()
        mock_config.api_keys = {ProviderName.RUNPOD: "test-key"}
        mock_config.ssh_key_path = str(tmp_path / "id_rsa")
        (tmp_path / "id_rsa.pub").write_text("ssh-rsa AAAA test")

        mock_provider = self._make_mock_provider("pod-456")
        mock_store = MagicMock()

        with patch("autofoundry.provisioner.get_provider", return_value=mock_provider):
            provision_instances(mock_config, plan, "op-1", mock_store)

        call_args = mock_provider.create_instance.call_args
        config = call_args[0][0]
        assert config.volume_id == ""
