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
