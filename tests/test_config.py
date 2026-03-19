"""Tests for configuration management."""

from pathlib import Path
from unittest.mock import patch

from autofoundry.config import Config
from autofoundry.models import ProviderName


class TestConfig:
    def test_save_and_load(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "autofoundry"
        config_file = config_dir / "config.toml"
        sessions_dir = config_dir / "sessions"

        with (
            patch("autofoundry.config.CONFIG_DIR", config_dir),
            patch("autofoundry.config.CONFIG_FILE", config_file),
            patch("autofoundry.config.SESSIONS_DIR", sessions_dir),
        ):
            config = Config()
            config.api_keys[ProviderName.RUNPOD] = "rp_test_key_123"
            config.api_keys[ProviderName.VASTAI] = "va_test_key_456"
            config.default_gpu_type = "A100"
            config.save()

            assert config_file.exists()

            loaded = Config.load()
            assert loaded is not None
            assert loaded.api_keys[ProviderName.RUNPOD] == "rp_test_key_123"
            assert loaded.api_keys[ProviderName.VASTAI] == "va_test_key_456"
            assert loaded.default_gpu_type == "A100"

    def test_load_returns_none_when_no_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "nonexistent" / "config.toml"
        with patch("autofoundry.config.CONFIG_FILE", config_file):
            assert Config.load() is None

    def test_configured_providers(self) -> None:
        config = Config()
        assert config.configured_providers == []

        config.api_keys[ProviderName.RUNPOD] = "key1"
        assert config.configured_providers == [ProviderName.RUNPOD]

        config.api_keys[ProviderName.PRIMEINTELLECT] = "key2"
        assert len(config.configured_providers) == 2

    def test_next_operation_id(self) -> None:
        config = Config()
        assert config.next_operation_id == "op-1"
        assert config.next_operation_id == "op-2"
        assert config.next_operation_id == "op-3"

    def test_save_and_load_segment_fields(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "autofoundry"
        config_file = config_dir / "config.toml"
        sessions_dir = config_dir / "sessions"

        with (
            patch("autofoundry.config.CONFIG_DIR", config_dir),
            patch("autofoundry.config.CONFIG_FILE", config_file),
            patch("autofoundry.config.SESSIONS_DIR", sessions_dir),
        ):
            config = Config()
            config.api_keys[ProviderName.RUNPOD] = "key"
            config.default_segment = "workstation"
            config.default_min_vram = 48.0
            config.save()

            loaded = Config.load()
            assert loaded.default_segment == "workstation"
            assert loaded.default_min_vram == 48.0

    def test_migrate_default_tier(self, tmp_path: Path) -> None:
        """Old default_tier in config.toml should migrate to segment + min_vram."""
        config_dir = tmp_path / "autofoundry"
        config_file = config_dir / "config.toml"
        sessions_dir = config_dir / "sessions"
        config_dir.mkdir(parents=True)
        sessions_dir.mkdir()

        config_file.write_text(
            'default_tier = "datacenter-80gb+"\n'
            "\n"
            "[api_keys]\n"
            'runpod = "test-key"\n'
        )

        with (
            patch("autofoundry.config.CONFIG_DIR", config_dir),
            patch("autofoundry.config.CONFIG_FILE", config_file),
            patch("autofoundry.config.SESSIONS_DIR", sessions_dir),
        ):
            loaded = Config.load()
            assert loaded.default_segment == "datacenter"
            assert loaded.default_min_vram == 80.0

    def test_no_image_fields(self) -> None:
        """Config should not have image-related fields after Docker removal."""
        config = Config()
        assert not hasattr(config, "last_image")
        assert not hasattr(config, "script_images")

    def test_load_ignores_legacy_image_fields(self, tmp_path: Path) -> None:
        """Loading a config with old image fields should not crash."""
        config_dir = tmp_path / "autofoundry"
        config_file = config_dir / "config.toml"
        sessions_dir = config_dir / "sessions"
        config_dir.mkdir(parents=True)
        sessions_dir.mkdir()

        # Write a config file with legacy fields
        config_file.write_text(
            'ssh_key_path = "/home/user/.ssh/id_rsa"\n'
            'default_gpu_type = "H100"\n'
            'last_script = "/tmp/run.sh"\n'
            'last_image = "user/repo:latest"\n'
            "next_operation = 5\n"
            "\n"
            "[api_keys]\n"
            'runpod = "test-key"\n'
            "\n"
            "[script_images]\n"
            '"/tmp/run.sh" = "user/repo:latest"\n'
        )

        with (
            patch("autofoundry.config.CONFIG_DIR", config_dir),
            patch("autofoundry.config.CONFIG_FILE", config_file),
            patch("autofoundry.config.SESSIONS_DIR", sessions_dir),
        ):
            loaded = Config.load()
            assert loaded is not None
            assert loaded.api_keys[ProviderName.RUNPOD] == "test-key"
            assert loaded._next_operation == 5
