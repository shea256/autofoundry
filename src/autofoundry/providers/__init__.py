"""Provider registry for GPU cloud backends."""

from __future__ import annotations

from typing import TYPE_CHECKING

from autofoundry.models import ProviderName

if TYPE_CHECKING:
    from autofoundry.providers.base import CloudProvider


def get_provider(
    name: ProviderName, api_key: str, *, min_bandwidth_mbps: float = 5000.0,
) -> CloudProvider:
    """Get an initialized provider instance by name."""
    if name == ProviderName.RUNPOD:
        from autofoundry.providers.runpod import RunPodProvider
        return RunPodProvider(api_key)
    elif name == ProviderName.VASTAI:
        from autofoundry.providers.vastai import VastAIProvider
        return VastAIProvider(api_key, min_bandwidth_mbps=min_bandwidth_mbps)
    elif name == ProviderName.PRIMEINTELLECT:
        from autofoundry.providers.primeintellect import PrimeIntellectProvider
        return PrimeIntellectProvider(api_key)
    elif name == ProviderName.LAMBDALABS:
        from autofoundry.providers.lambdalabs import LambdaLabsProvider
        return LambdaLabsProvider(api_key)
    else:
        raise ValueError(f"Unknown provider: {name}")
