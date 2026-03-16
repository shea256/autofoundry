"""Configuration management and first-run setup."""

from __future__ import annotations

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
        self.default_gpu_type: str = "H100"
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
            "last_script": self.last_script,
            "next_operation": self._next_operation,
            "api_keys": {p.value: key for p, key in self.api_keys.items()},
        }
        CONFIG_FILE.write_text(_serialize_toml(data))

    @classmethod
    def load(cls) -> Config | None:
        """Load config from disk. Returns None if no config file exists."""
        if not CONFIG_FILE.exists():
            return None

        config = cls()
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)

        config.ssh_key_path = data.get("ssh_key_path", config.ssh_key_path)
        config.default_gpu_type = data.get("default_gpu_type", config.default_gpu_type)
        config.last_script = data.get("last_script", "")
        config._next_operation = data.get("next_operation", 1)

        api_keys = data.get("api_keys", {})
        for provider in ProviderName:
            key = api_keys.get(provider.value, "")
            if key:
                config.api_keys[provider] = key

        return config


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

    config.save()
    console.print()
    print_success("Configuration saved")
    print_status("Config file", str(CONFIG_FILE))
    print_status("Providers", ", ".join(PROVIDER_DISPLAY[p] for p in config.configured_providers))

    return config
