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
}


def _provision_one(
    provider: CloudProvider,
    config: InstanceConfig,
    unit_num: int,
) -> InstanceInfo:
    """Create a single instance and wait for it to be ready."""
    display = provider.name
    console.print(
        f"  [af.muted]UNIT-{unit_num:02d} [{display}] creating...[/af.muted]"
    )

    info = provider.create_instance(config)
    console.print(
        f"  [af.secondary]UNIT-{unit_num:02d} [{display}] "
        f"instance {info.instance_id} — waiting for SSH...[/af.secondary]"
    )

    info = provider.wait_until_ready(info.instance_id, timeout=600)
    console.print(
        f"  [af.success]UNIT-{unit_num:02d} [{display}] "
        f"ONLINE @ {info.ssh.host}:{info.ssh.port}[/af.success]"
    )
    return info


def provision_instances(
    config: Config,
    plan: ProvisioningPlan,
    session_id: str,
    store: SessionStore,
) -> list[InstanceInfo]:
    """Provision all instances in the plan in parallel."""
    print_header(f"{TERMS['provisioning']}")
    console.print()

    # Build list of (provider, instance_config, unit_number) tasks
    tasks: list[tuple[CloudProvider, InstanceConfig, int]] = []
    unit_num = 1

    for offer, count in plan.offers:
        provider = get_provider(offer.provider, config.api_keys[offer.provider])
        for _ in range(count):
            instance_config = InstanceConfig(
                name=f"af-{session_id}-unit{unit_num:02d}",
                gpu_type=offer.gpu_type,
                gpu_count=offer.gpu_count,
                image=PROVIDER_IMAGES.get(
                    offer.provider,
                    "pytorch/pytorch:2.6.0-cuda12.6-cudnn9-devel",
                ),
                disk_gb=50,
                ssh_public_key=_read_ssh_public_key(config.ssh_key_path),
                offer_id=offer.offer_id,
                metadata=offer.metadata,
            )
            tasks.append((provider, instance_config, unit_num))
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
            pool.submit(_provision_one, provider, ic, num): num
            for provider, ic, num in tasks
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
