"""Tests for CLI commands and volume resolution."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from autofoundry.cli import app
from autofoundry.models import ProviderName, VolumeInfo

runner = CliRunner()


class TestCLIHelp:
    def test_bare_invocation_shows_help(self) -> None:
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "COMMANDS" in result.output
        assert "config" in result.output
        assert "run" in result.output
        assert "volumes" in result.output

    def test_no_build_command(self) -> None:
        """build command should no longer exist."""
        result = runner.invoke(app, ["build", "--help"])
        assert result.exit_code != 0

    def test_no_image_flag_on_run(self) -> None:
        """--image flag should no longer exist on run."""
        result = runner.invoke(app, ["run", "--help"])
        assert "--image" not in result.output

    def test_volume_flag_on_run(self) -> None:
        """--volume flag should be present on run."""
        result = runner.invoke(app, ["run", "--help"])
        assert "--volume" in result.output


class TestVolumesCommand:
    def test_bare_volumes_shows_subcommands(self) -> None:
        result = runner.invoke(app, ["volumes"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "create" in result.output

    def test_no_volume_providers(self) -> None:
        mock_config = MagicMock()
        mock_config.configured_providers = [ProviderName.PRIMEINTELLECT]

        with patch("autofoundry.cli._load_or_setup_config", return_value=mock_config):
            result = runner.invoke(app, ["volumes", "list"])

        assert result.exit_code == 0
        assert "No providers with volume support" in result.output

    def test_lists_volumes(self) -> None:
        mock_config = MagicMock()
        mock_config.configured_providers = [ProviderName.RUNPOD]
        mock_config.api_keys = {ProviderName.RUNPOD: "test-key"}

        mock_provider = MagicMock()
        mock_provider.list_volumes.return_value = [
            VolumeInfo(
                provider=ProviderName.RUNPOD,
                volume_id="vol-abc123def456",
                name="my-vol",
                size_gb=100,
                region="US-TX-3",
                mount_path="/workspace",
            ),
        ]

        with (
            patch("autofoundry.cli._load_or_setup_config", return_value=mock_config),
            patch("autofoundry.providers.get_provider", return_value=mock_provider),
        ):
            result = runner.invoke(app, ["volumes", "list"])

        assert result.exit_code == 0
        assert "my-vol" in result.output
        assert "100GB" in result.output

    def test_no_volumes_found(self) -> None:
        mock_config = MagicMock()
        mock_config.configured_providers = [ProviderName.RUNPOD]
        mock_config.api_keys = {ProviderName.RUNPOD: "test-key"}

        mock_provider = MagicMock()
        mock_provider.list_volumes.return_value = []

        with (
            patch("autofoundry.cli._load_or_setup_config", return_value=mock_config),
            patch("autofoundry.providers.get_provider", return_value=mock_provider),
        ):
            result = runner.invoke(app, ["volumes", "list"])

        assert result.exit_code == 0
        assert "No volumes found" in result.output


class TestVolumesCreateCommand:
    def test_create_runpod_volume_all_flags(self) -> None:
        mock_config = MagicMock()
        mock_config.configured_providers = [ProviderName.RUNPOD]
        mock_config.api_keys = {ProviderName.RUNPOD: "test-key"}

        mock_provider = MagicMock()
        mock_provider.create_volume.return_value = VolumeInfo(
            provider=ProviderName.RUNPOD,
            volume_id="vol-new123",
            name="test-vol",
            size_gb=50,
            region="US-TX-3",
            mount_path="/workspace",
        )

        with (
            patch("autofoundry.cli._load_or_setup_config", return_value=mock_config),
            patch("autofoundry.providers.get_provider", return_value=mock_provider),
        ):
            result = runner.invoke(
                app,
                ["volumes", "create", "-n", "test-vol", "-p", "runpod", "-s", "50", "-r", "US-TX-3"],
                input="y\n",
            )

        assert result.exit_code == 0
        assert "Volume created" in result.output
        assert "test-vol" in result.output
        mock_provider.create_volume.assert_called_once_with("test-vol", 50, "US-TX-3")

    def test_create_no_providers(self) -> None:
        mock_config = MagicMock()
        mock_config.configured_providers = [ProviderName.PRIMEINTELLECT]

        with patch("autofoundry.cli._load_or_setup_config", return_value=mock_config):
            result = runner.invoke(app, ["volumes", "create", "-n", "test-vol"])

        assert result.exit_code == 0
        assert "No providers with volume support" in result.output


class TestResolveVolume:
    def test_finds_existing_volume(self) -> None:
        from autofoundry.cli import _resolve_volume

        mock_config = MagicMock()
        mock_config.api_keys = {ProviderName.RUNPOD: "test-key"}

        mock_provider = MagicMock()
        mock_provider.list_volumes.return_value = [
            VolumeInfo(
                provider=ProviderName.RUNPOD,
                volume_id="vol-123",
                name="my-vol",
                size_gb=100,
                region="US-TX-3",
                mount_path="/workspace",
            ),
        ]

        with patch("autofoundry.providers.get_provider", return_value=mock_provider):
            result = _resolve_volume(
                mock_config, "my-vol", {ProviderName.RUNPOD}
            )

        assert result == "vol-123"

    def test_unsupported_provider_returns_empty(self) -> None:
        from autofoundry.cli import _resolve_volume

        mock_config = MagicMock()
        result = _resolve_volume(
            mock_config, "my-vol", {ProviderName.PRIMEINTELLECT}
        )
        assert result == ""

    def test_no_volume_support_returns_empty(self) -> None:
        from autofoundry.cli import _resolve_volume

        mock_config = MagicMock()
        mock_config.api_keys = {ProviderName.RUNPOD: "test-key"}

        mock_provider = MagicMock(spec=[])  # no list_volumes attribute

        with patch("autofoundry.providers.get_provider", return_value=mock_provider):
            result = _resolve_volume(
                mock_config, "my-vol", {ProviderName.RUNPOD}
            )

        assert result == ""
