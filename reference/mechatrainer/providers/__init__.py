"""
Provider registry and utilities.
"""

from typing import Dict, Any, Optional
from . import runpod, vastai, primeintellect

# Registry of providers
_PROVIDERS = {
    "runpod": {
        "get_preset": runpod.get_preset,
        "format_details": runpod.format_pod_details,
        "list_profiles": runpod.list_profiles,
        "API": runpod.API,
    },
    "vastai": {
        "get_preset": vastai.get_preset,
        "format_details": vastai.format_instance_details,
        "list_profiles": vastai.list_profiles,
        "API": vastai.API,
    },
    "primeintellect": {
        "get_preset": primeintellect.get_preset,
        "format_details": primeintellect.format_pod_details,
        "list_profiles": primeintellect.list_profiles,
        "API": primeintellect.API,
    },
}


def get_api_class(provider: str):
    """Get the API class for a provider."""
    if provider in _PROVIDERS:
        return _PROVIDERS[provider]["API"]
    return None


def get_preset(profile: str, provider: str) -> Dict[str, Any]:
    """Get configuration preset for a profile and provider."""
    if provider in _PROVIDERS:
        return _PROVIDERS[provider]["get_preset"](profile)
    return {}


def format_details(data: Dict[str, Any], provider: str) -> str:
    """Format pod/instance details for display."""
    if provider in _PROVIDERS:
        return _PROVIDERS[provider]["format_details"](data)
    return str(data)


def list_providers() -> list[str]:
    """List all available providers."""
    return list(_PROVIDERS.keys())


def list_profiles(provider: Optional[str] = None) -> list[str]:
    """List all available profiles."""
    if provider:
        if provider in _PROVIDERS:
            return _PROVIDERS[provider]["list_profiles"]()
        return []
    
    # Collect all unique profiles across all providers
    all_profiles = set()
    for provider_info in _PROVIDERS.values():
        all_profiles.update(provider_info["list_profiles"]())
    return sorted(list(all_profiles))

