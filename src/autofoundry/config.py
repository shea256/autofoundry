"""Configuration management and first-run setup."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from rich.prompt import Confirm, Prompt

from autofoundry.models import ProviderName
from autofoundry.theme import console, print_error, print_header, print_status, print_success

CONFIG_DIR = Path.home() / ".config" / "autofoundry"
CONFIG_FILE = CONFIG_DIR / "config.toml"
SESSIONS_DIR = CONFIG_DIR / "sessions"

PROVIDER_DISPLAY = {
    ProviderName.RUNPOD: "RunPod",
    ProviderName.VASTAI: "Vast.ai",
    ProviderName.PRIMEINTELLECT: "PRIME Intellect",
    ProviderName.LAMBDALABS: "Lambda Labs",
}

# Env var names for provider API keys (fallback when not in config.toml)
PROVIDER_ENV_VARS = {
    ProviderName.RUNPOD: "RUNPOD_API_KEY",
    ProviderName.VASTAI: "VASTAI_API_KEY",
    ProviderName.PRIMEINTELLECT: "PRIMEINTELLECT_API_KEY",
    ProviderName.LAMBDALABS: "LAMBDALABS_API_KEY",
}


def _serialize_toml(data: dict) -> str:
    """Serialize a dict to TOML format (simple flat/section serializer)."""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"\n[{key}]")
            for k, v in value.items():
                lines.append(f'{k} = "{v}"')
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        else:
            lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"


class Config:
    """Autofoundry configuration."""

    def __init__(self) -> None:
        self.api_keys: dict[ProviderName, str] = {}
        self.ssh_key_path: str = str(Path.home() / ".ssh" / "id_rsa")
        self.default_gpu_type: str = "H100"  # legacy, kept for backward compat
        self.default_segment: str = "datacenter"
        self.default_min_vram: float | None = 80.0
        self.min_bandwidth_mbps: float = 5000.0
        self.huggingface_token: str = ""
        self.last_script: str = ""
        self._next_operation: int = 1

    @property
    def configured_providers(self) -> list[ProviderName]:
        return [p for p, key in self.api_keys.items() if key]

    @property
    def next_operation_id(self) -> str:
        op_id = f"op-{self._next_operation}"
        self._next_operation += 1
        return op_id

    def save(self) -> None:
        """Save config to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

        data: dict = {
            "ssh_key_path": self.ssh_key_path,
            "default_gpu_type": self.default_gpu_type,
            "default_segment": self.default_segment,
            "default_min_vram": self.default_min_vram if self.default_min_vram is not None else "",
            "min_bandwidth_mbps": self.min_bandwidth_mbps,
            "huggingface_token": self.huggingface_token,
            "last_script": self.last_script,
            "next_operation": self._next_operation,
            "api_keys": {p.value: key for p, key in self.api_keys.items()},
        }
        CONFIG_FILE.write_text(_serialize_toml(data))

    @classmethod
    def load(cls) -> Config | None:
        """Load config from disk. Returns None if no config file exists.

        Precedence: config.toml > env vars/.env > defaults.
        """
        if not CONFIG_FILE.exists():
            return cls._from_env()

        config = cls()
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)

        config.ssh_key_path = data.get("ssh_key_path", config.ssh_key_path)
        config.default_gpu_type = data.get("default_gpu_type", config.default_gpu_type)
        config.min_bandwidth_mbps = float(data.get("min_bandwidth_mbps", config.min_bandwidth_mbps))

        # Load segment/min_vram, migrating from old default_tier if present
        if "default_segment" in data:
            config.default_segment = data["default_segment"]
            raw_vram = data.get("default_min_vram", "")
            config.default_min_vram = float(raw_vram) if raw_vram != "" else None
        elif "default_tier" in data:
            config._migrate_default_tier(data["default_tier"])
        config.huggingface_token = data.get("huggingface_token", "")
        config.last_script = data.get("last_script", "")
        config._next_operation = data.get("next_operation", 1)

        api_keys = data.get("api_keys", {})
        for provider in ProviderName:
            key = api_keys.get(provider.value, "")
            if key:
                config.api_keys[provider] = key

        # Fill gaps from env vars (config.toml values take precedence)
        config._apply_env_fallbacks()

        return config

    @classmethod
    def _from_env(cls) -> Config | None:
        """Try to build a config purely from env vars. Returns None if no keys found."""
        config = cls()
        config._apply_env_fallbacks()
        if not config.configured_providers:
            return None
        return config

    def _migrate_default_tier(self, tier_name: str) -> None:
        """Migrate old default_tier value to segment + min_vram."""
        from autofoundry.gpu_filter import TIER_BY_NAME

        # Try direct lookup
        tier = TIER_BY_NAME.get(tier_name)
        if tier:
            self.default_segment = tier.category
            self.default_min_vram = tier.vram_min
            return

        # Try parsing "category-NNgb+" format
        if "-" in tier_name:
            parts = tier_name.rsplit("-", 1)
            self.default_segment = parts[0]
            vram_part = parts[1].lower().replace("gb+", "").replace("gb", "")
            try:
                self.default_min_vram = float(vram_part)
            except ValueError:
                pass

    def _apply_env_fallbacks(self) -> None:
        """Fill missing config values from environment variables."""
        for provider, env_var in PROVIDER_ENV_VARS.items():
            if provider not in self.api_keys:
                key = os.environ.get(env_var, "")
                if key:
                    self.api_keys[provider] = key

        if not self.huggingface_token:
            self.huggingface_token = os.environ.get("HUGGINGFACE_TOKEN", "")

        env_ssh = os.environ.get("AUTOFOUNDRY_SSH_KEY_PATH", "")
        if env_ssh:
            self.ssh_key_path = env_ssh

        env_gpu = os.environ.get("AUTOFOUNDRY_GPU_TYPE", "")
        if env_gpu:
            self.default_gpu_type = env_gpu

        env_bw = os.environ.get("AUTOFOUNDRY_MIN_BANDWIDTH_MBPS", "")
        if env_bw:
            self.min_bandwidth_mbps = float(env_bw)


def first_run_setup(existing: Config | None = None) -> Config:
    """Interactive configuration. Preserves existing provider keys by default."""
    print_header("FIRST CONTACT PROTOCOL — SUPPLY LINE CONFIGURATION")
    console.print()
    console.print("  [af.muted]Configure your GPU cloud provider API keys.[/af.muted]")
    console.print("  [af.muted]You need at least one provider to proceed.[/af.muted]")
    console.print()

    config = existing if existing is not None else Config()

    for provider in ProviderName:
        display = PROVIDER_DISPLAY[provider]
        already_configured = provider in config.api_keys

        if already_configured:
            console.print(f"  [af.secondary]{display}[/af.secondary] — [af.muted]configured ✓[/af.muted]")
            if Confirm.ask(f"    Reconfigure [af.secondary]{display}[/af.secondary]?", default=False):
                key = Prompt.ask(f"    [af.label]{display} API key[/af.label]")
                if key.strip():
                    config.api_keys[provider] = key.strip()
                    print_success(f"{display} key updated")
                else:
                    print_error(f"Empty key, keeping existing")
        else:
            if Confirm.ask(f"  Configure [af.secondary]{display}[/af.secondary]?", default=True):
                key = Prompt.ask(f"    [af.label]{display} API key[/af.label]")
                if key.strip():
                    config.api_keys[provider] = key.strip()
                    print_success(f"{display} key stored")
                else:
                    print_error(f"Empty key, skipping {display}")
        console.print()

    if not config.configured_providers:
        print_error("No providers configured. At least one is required.")
        raise SystemExit(1)

    # SSH key
    ssh_path = Prompt.ask(
        "  [af.label]SSH private key path[/af.label]",
        default=config.ssh_key_path,
    )
    config.ssh_key_path = ssh_path
    console.print()

    # Default GPU
    config.default_gpu_type = Prompt.ask(
        "  [af.label]Default GPU type[/af.label]",
        default=config.default_gpu_type,
    )

    # Minimum bandwidth
    bw = Prompt.ask(
        "  [af.label]Min download bandwidth (Mbps)[/af.label]",
        default=str(int(config.min_bandwidth_mbps)),
    )
    config.min_bandwidth_mbps = float(bw)

    # HuggingFace token (optional)
    console.print()
    hf_default = config.huggingface_token or ""
    hf_hint = " [af.muted](configured ✓)[/af.muted]" if hf_default else " [af.muted](optional)[/af.muted]"
    hf_token = Prompt.ask(
        f"  [af.label]HuggingFace token[/af.label]{hf_hint}",
        default=hf_default,
    )
    config.huggingface_token = hf_token.strip()

    config.save()
    console.print()
    print_success("Configuration saved")
    print_status("Config file", str(CONFIG_FILE))
    print_status("Providers", ", ".join(PROVIDER_DISPLAY[p] for p in config.configured_providers))

    return config
