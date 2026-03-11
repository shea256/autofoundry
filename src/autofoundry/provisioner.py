"""Instance provisioning and lifecycle management."""

from __future__ import annotations

import signal
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from autofoundry.config import PROVIDER_DISPLAY, Config
from autofoundry.models import (
    InstanceConfig,
    InstanceInfo,
    ProviderName,
    ProvisioningPlan,
)
from autofoundry.providers import get_provider
from autofoundry.providers.base import CloudProvider
from autofoundry.state import SessionStore
from autofoundry.theme import (
    TERMS,
    console,
    print_error,
    print_header,
    print_success,
)

# Provider-native default images — latest CUDA available per platform
PROVIDER_IMAGES: dict[ProviderName, str] = {
    ProviderName.RUNPOD: "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
    ProviderName.VASTAI: "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
    ProviderName.PRIMEINTELLECT: "cuda_12_4_pytorch_2_4",
    ProviderName.LAMBDALABS: "",  # Lambda uses pre-configured Ubuntu images, not Docker
}


MAX_OFFER_RETRIES = 5


def _provision_one(
    provider: CloudProvider,
    config: InstanceConfig,
    unit_num: int,
    gpu_type: str | None = None,
) -> InstanceInfo:
    """Create a single instance and wait for it to be ready.

    If the initial offer is taken, queries fresh offers and retries
    with the next cheapest available (up to MAX_OFFER_RETRIES attempts).
    """
    display = provider.name
    label = f"UNIT-{unit_num:02d}"
    tried_offers: set[str] = set()
    current_config = config

    for attempt in range(MAX_OFFER_RETRIES):
        tried_offers.add(current_config.offer_id)
        console.print(
            f"  [af.muted]{label} [{display}] creating "
            f"(offer {current_config.offer_id[:12]})...[/af.muted]"
        )

        try:
            info = provider.create_instance(current_config)
            console.print(
                f"  [af.secondary]{label} [{display}] "
                f"instance {info.instance_id} — waiting for SSH...[/af.secondary]"
            )
            info = provider.wait_until_ready(info.instance_id, timeout=900)
            console.print(
                f"  [af.success]{label} [{display}] "
                f"ONLINE @ {info.ssh.host}:{info.ssh.port}[/af.success]"
            )
            return info

        except Exception as e:
            error_msg = str(e).lower()
            # Retryable errors: offer taken, no longer available
            retryable = any(kw in error_msg for kw in (
                "no_such_ask", "not found", "no longer available",
                "unavailable", "already rented",
            ))

            if not retryable or attempt >= MAX_OFFER_RETRIES - 1:
                raise

            console.print(
                f"  [af.muted]{label} [{display}] offer taken, "
                f"finding next available...[/af.muted]"
            )

            # Query fresh offers and pick the cheapest untried one
            fresh_offers = provider.list_gpu_offers(gpu_type)
            fresh_offers.sort(key=lambda o: o.price_per_hour)

            next_offer = None
            for offer in fresh_offers:
                if offer.offer_id not in tried_offers and offer.availability > 0:
                    next_offer = offer
                    break

            if next_offer is None:
                raise RuntimeError(
                    f"No more {gpu_type or 'GPU'} offers available on {display} "
                    f"(tried {len(tried_offers)})"
                )

            current_config = current_config.model_copy(
                update={"offer_id": next_offer.offer_id}
            )

    raise RuntimeError(f"Failed to provision {label} after {MAX_OFFER_RETRIES} attempts")


def provision_instances(
    config: Config,
    plan: ProvisioningPlan,
    session_id: str,
    store: SessionStore,
    custom_image: str | None = None,
    gpu_type_filter: str | None = None,
) -> list[InstanceInfo]:
    """Provision all instances in the plan in parallel.

    Args:
        custom_image: If provided, use this Docker image instead of the provider default.
        gpu_type_filter: User's original GPU search term (e.g., "H100") for retry queries.
            If None, falls back to the specific offer's gpu_type.
    """
    print_header(f"{TERMS['provisioning']}")
    console.print()

    # Build list of (provider, instance_config, unit_number, gpu_type) tasks
    tasks: list[tuple[CloudProvider, InstanceConfig, int, str]] = []
    unit_num = 1

    for offer, count in plan.offers:
        provider = get_provider(offer.provider, config.api_keys[offer.provider])
        for _ in range(count):
            image = custom_image or PROVIDER_IMAGES.get(
                offer.provider,
                "pytorch/pytorch:2.6.0-cuda12.6-cudnn9-devel",
            )
            instance_config = InstanceConfig(
                name=f"af-{session_id}-unit{unit_num:02d}",
                gpu_type=offer.gpu_type,
                gpu_count=offer.gpu_count,
                image=image,
                disk_gb=50,
                ssh_public_key=_read_ssh_public_key(config.ssh_key_path),
                offer_id=offer.offer_id,
                metadata=offer.metadata,
            )
            retry_gpu = gpu_type_filter or offer.gpu_type
            tasks.append((provider, instance_config, unit_num, retry_gpu))
            unit_num += 1

    total = len(tasks)
    console.print(
        f"  [af.primary]Activating {total} {TERMS['instances'].lower()}...[/af.primary]"
    )
    console.print()

    instances: list[InstanceInfo] = []
    failed = 0

    with ThreadPoolExecutor(max_workers=min(total, 4)) as pool:
        futures = {
            pool.submit(_provision_one, provider, ic, num, gpu): num
            for provider, ic, num, gpu in tasks
        }
        for future in as_completed(futures):
            num = futures[future]
            try:
                info = future.result()
                info = info.model_copy(
                    update={"created_at": datetime.now()}
                )
                instances.append(info)
                store.add_instance(info)
            except Exception as e:
                failed += 1
                print_error(f"UNIT-{num:02d} failed: {e}")

    console.print()
    if instances:
        print_success(
            f"{len(instances)}/{total} {TERMS['instances'].lower()} online"
        )
    if failed:
        print_error(
            f"{failed} {TERMS['instances'].lower()} failed to activate"
        )
    console.print()

    return instances


def stop_instances(
    config: Config, instances: list[InstanceInfo]
) -> None:
    """Stop all provisioned instances (keeps disk, releases GPU)."""
    if not instances:
        return

    print_header("STANDBY PROTOCOL")
    console.print()

    for info in instances:
        try:
            provider = get_provider(info.provider, config.api_keys[info.provider])
            if hasattr(provider, "stop_instance"):
                provider.stop_instance(info.instance_id)
                display = PROVIDER_DISPLAY.get(info.provider, info.provider.value)
                print_success(f"{info.name} [{display}] stopped (disk preserved)")
            else:
                display = PROVIDER_DISPLAY.get(info.provider, info.provider.value)
                console.print(
                    f"  [af.muted]{info.name} [{display}] — stop not supported, "
                    f"keeping running[/af.muted]"
                )
        except Exception as e:
            print_error(f"Failed to stop {info.name}: {e}")

    console.print()


def teardown_instances(
    config: Config, instances: list[InstanceInfo]
) -> None:
    """Delete all provisioned instances."""
    if not instances:
        return

    print_header(TERMS["shutdown"])
    console.print()

    for info in instances:
        try:
            provider = get_provider(info.provider, config.api_keys[info.provider])
            provider.delete_instance(info.instance_id)
            display = PROVIDER_DISPLAY.get(info.provider, info.provider.value)
            print_success(f"{info.name} [{display}] terminated")
        except Exception as e:
            print_error(f"Failed to delete {info.name}: {e}")

    console.print()


def register_cleanup_handler(
    config: Config, instances: list[InstanceInfo]
) -> None:
    """Register SIGINT/SIGTERM handler to clean up instances on exit."""
    def handler(signum: int, frame: object) -> None:
        console.print()
        console.print("  [af.alert]INTERRUPT — initiating cleanup...[/af.alert]")
        teardown_instances(config, instances)
        sys.exit(1)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _read_ssh_public_key(private_key_path: str) -> str:
    """Read the SSH public key corresponding to a private key path."""
    from pathlib import Path

    pub_path = Path(private_key_path + ".pub")
    if pub_path.exists():
        return pub_path.read_text().strip()
    return ""
