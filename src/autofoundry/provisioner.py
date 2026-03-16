"""Instance provisioning and lifecycle management."""

from __future__ import annotations

import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from autofoundry.config import PROVIDER_DISPLAY, Config
from autofoundry.models import (
    InstanceConfig,
    InstanceInfo,
    InstanceStatus,
    ProviderName,
    ProvisioningPlan,
)
from autofoundry.providers import get_provider
from autofoundry.providers.base import CloudProvider
from autofoundry.state import SessionStore
from autofoundry.theme import (
    TERMS,
    console,
    display_status,
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


class ProvisioningError(Exception):
    """Error during provisioning that may include a partially-created instance."""

    def __init__(self, message: str, partial_instance: InstanceInfo | None = None):
        super().__init__(message)
        self.partial_instance = partial_instance


def _provision_one(
    provider: CloudProvider,
    config: InstanceConfig,
    unit_num: int,
    gpu_type: str | None = None,
    shared_claimed: set[str] | None = None,
    claimed_lock: threading.Lock | None = None,
    cancel_event: threading.Event | None = None,
) -> InstanceInfo:
    """Create a single instance and wait for it to be ready.

    If the initial offer is taken, queries fresh offers and retries
    with the next cheapest available (up to MAX_OFFER_RETRIES attempts).

    Args:
        shared_claimed: Offer IDs already claimed by other threads (avoids retry storms).
        claimed_lock: Lock protecting shared_claimed.
        cancel_event: Set by main thread on Ctrl+C to signal workers to stop.
    """
    display = provider.name
    label = f"UNIT-{unit_num:02d}"
    current_config = config

    def _claim_offer(offer_id: str) -> None:
        if shared_claimed is not None and claimed_lock is not None:
            with claimed_lock:
                shared_claimed.add(offer_id)

    def _is_claimed(offer_id: str) -> bool:
        if shared_claimed is not None and claimed_lock is not None:
            with claimed_lock:
                return offer_id in shared_claimed
        return False

    _claim_offer(current_config.offer_id)

    for attempt in range(MAX_OFFER_RETRIES):
        console.print(
            f"  [af.muted]{label} [{display}] creating "
            f"({current_config.gpu_type} {current_config.offer_id[:12]})...[/af.muted]"
        )

        try:
            info = provider.create_instance(current_config)
            break  # Creation succeeded, proceed to wait
        except Exception as e:
            error_msg = str(e).lower()
            # Retryable errors: offer taken, no longer available
            retryable = any(kw in error_msg for kw in (
                "no_such_ask", "not found", "no longer available",
                "unavailable", "already rented", "insufficient capacity",
                "try again later", "out of stock", "503",
                "no instances", "currently available",
            ))

            if not retryable or attempt >= MAX_OFFER_RETRIES - 1:
                raise

            console.print(
                f"  [af.muted]{label} [{display}] unit taken, "
                f"finding next available...[/af.muted]"
            )

            # Query fresh offers and pick the cheapest one not claimed by any thread
            fresh_offers = provider.list_gpu_offers(gpu_type)
            fresh_offers.sort(key=lambda o: o.price_per_hour)

            next_offer = None
            for offer in fresh_offers:
                if not _is_claimed(offer.offer_id) and offer.availability > 0:
                    next_offer = offer
                    _claim_offer(offer.offer_id)
                    break

            if next_offer is None:
                raise RuntimeError(
                    f"No more {gpu_type or 'GPU'} offers available on {display}"
                )

            current_config = current_config.model_copy(
                update={"offer_id": next_offer.offer_id}
            )
    else:
        raise RuntimeError(f"Failed to provision {label} after {MAX_OFFER_RETRIES} attempts")

    # Instance created — poll for SSH readiness with status updates
    console.print(
        f"  [af.secondary]{label} [{display}] "
        f"instance {info.instance_id} — waiting for SSH...[/af.secondary]"
    )
    import time as _time

    timeout = 900
    start = _time.time()
    deadline = start + timeout
    delay = 5.0
    last_status = ""
    poll_count = 0
    try:
        while _time.time() < deadline:
            if cancel_event and cancel_event.is_set():
                raise ProvisioningError(
                    f"{label} cancelled", partial_instance=info
                )
            info = provider.get_instance(info.instance_id)
            status_str = info.status.value if info.status else "unknown"
            poll_count += 1
            elapsed = int(_time.time() - start)
            ssh_indicator = f", ssh={'yes' if info.ssh else 'no'}"
            if status_str != last_status:
                console.print(
                    f"  [af.muted]{label} [{display}] status: {status_str}{ssh_indicator}[/af.muted]"
                )
                last_status = status_str
            elif poll_count % 6 == 0:
                # Heartbeat every ~6 polls so the user knows we're still waiting
                console.print(
                    f"  [af.muted]{label} [{display}] still {status_str}{ssh_indicator} ({elapsed}s)[/af.muted]"
                )
            if info.status == InstanceStatus.RUNNING and info.ssh:
                break
            if info.status == InstanceStatus.ERROR:
                raise ProvisioningError(
                    f"{label} instance failed (status: {status_str})",
                    partial_instance=info,
                )
            # Use cancel_event.wait() instead of time.sleep() so cancellation
            # is noticed immediately rather than after the sleep finishes
            sleep_dur = min(delay, max(0, deadline - _time.time()))
            if cancel_event:
                cancel_event.wait(timeout=sleep_dur)
            else:
                _time.sleep(sleep_dur)
            delay = min(delay * 1.5, 30.0)
        else:
            raise TimeoutError(
                f"Instance {info.instance_id} not ready within {timeout}s "
                f"(last status: {last_status})"
            )
    except TimeoutError:
        raise ProvisioningError(
            f"Timed out waiting for {label} (status: {last_status})",
            partial_instance=info,
        )
    except Exception as e:
        raise ProvisioningError(str(e), partial_instance=info) from e

    console.print(
        f"  [af.success]{label} [{display}] "
        f"ONLINE @ {info.ssh.host}:{info.ssh.port}[/af.success]"
    )
    return info


def provision_instances(
    config: Config,
    plan: ProvisioningPlan,
    session_id: str,
    store: SessionStore,
    gpu_type_filter: str | None = None,
    volume_id: str = "",
    volume_region: str = "",
) -> list[InstanceInfo]:
    """Provision all instances in the plan in parallel.

    Args:
        gpu_type_filter: User's original GPU search term (e.g., "H100") for retry queries.
            If None, falls back to the specific offer's gpu_type.
        volume_id: Network volume ID to attach to instances.
        volume_region: Region/datacenter of the volume (for co-location).
    """
    print_header(f"{TERMS['provisioning']}")
    console.print()

    # Build list of (provider, instance_config, unit_number, gpu_type) tasks
    tasks: list[tuple[CloudProvider, InstanceConfig, int, str]] = []
    unit_num = 1
    ssh_pub_key = _read_ssh_public_key(config.ssh_key_path)

    # Shared set of claimed offer IDs so parallel threads don't fight over the same offers
    shared_claimed: set[str] = set()
    claimed_lock = threading.Lock()
    cancel_event = threading.Event()

    for offer, count in plan.offers:
        provider = get_provider(offer.provider, config.api_keys[offer.provider])
        image = PROVIDER_IMAGES.get(
            offer.provider,
            "pytorch/pytorch:2.6.0-cuda12.6-cudnn9-devel",
        )
        retry_gpu = gpu_type_filter or offer.gpu_type

        # When requesting multiple units, pre-fetch distinct offers so each
        # unit gets its own machine instead of all competing for one offer.
        if count > 1:
            all_offers = provider.list_gpu_offers(retry_gpu)
            all_offers.sort(key=lambda o: o.price_per_hour)
            # Start with the selected offer, then fill with the cheapest alternatives
            distinct_offers = [offer]
            seen_ids = {offer.offer_id}
            for o in all_offers:
                if o.offer_id not in seen_ids and o.availability > 0:
                    distinct_offers.append(o)
                    seen_ids.add(o.offer_id)
                if len(distinct_offers) >= count:
                    break
            if len(distinct_offers) < count:
                console.print(
                    f"  [af.alert]Only {len(distinct_offers)} distinct {retry_gpu} "
                    f"offers available (requested {count})[/af.alert]"
                )
        else:
            distinct_offers = [offer]

        for i in range(min(count, len(distinct_offers))):
            selected = distinct_offers[i]
            instance_config = InstanceConfig(
                name=f"af-{session_id}-unit{unit_num:02d}",
                gpu_type=selected.gpu_type,
                gpu_count=selected.gpu_count,
                image=image,
                disk_gb=50,
                ssh_public_key=ssh_pub_key,
                offer_id=selected.offer_id,
                volume_id=volume_id,
                volume_region=volume_region,
                metadata=selected.metadata,
            )
            shared_claimed.add(selected.offer_id)
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
            pool.submit(
                _provision_one, provider, ic, num, gpu,
                shared_claimed, claimed_lock, cancel_event,
            ): num
            for provider, ic, num, gpu in tasks
        }
        try:
            for future in as_completed(futures):
                num = futures[future]
                try:
                    info = future.result()
                    info = info.model_copy(
                        update={"created_at": datetime.now()}
                    )
                    instances.append(info)
                    store.add_instance(info)
                except ProvisioningError as e:
                    failed += 1
                    if not cancel_event.is_set():
                        print_error(f"UNIT-{num:02d} failed: {e}")
                    # Track partially-created instances so they get cleaned up
                    if e.partial_instance:
                        partial = e.partial_instance.model_copy(
                            update={"created_at": datetime.now()}
                        )
                        instances.append(partial)
                        store.add_instance(partial)
                except Exception as e:
                    failed += 1
                    if not cancel_event.is_set():
                        print_error(f"UNIT-{num:02d} failed: {e}")
        except KeyboardInterrupt:
            # Signal all worker threads to stop, then wait for them to finish
            cancel_event.set()
            for f in futures:
                f.cancel()
            # Drain remaining futures so partial instances get tracked
            for future in futures:
                try:
                    future.result()
                except ProvisioningError as e:
                    if e.partial_instance:
                        store.add_instance(e.partial_instance)
                except Exception:
                    pass
            raise

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


def restart_instances(
    config: Config,
    stored_instances: list[InstanceInfo],
    store: SessionStore,
) -> list[InstanceInfo]:
    """Restart stopped instances from a previous session.

    Queries each provider for current status, restarts stopped instances,
    and waits for SSH. Returns the list of instances that came back online.
    Instances that are already running are included as-is.
    Lost instances (deleted/errored) are reported.
    """
    print_header("REACTIVATION TEST")
    console.print()

    if not stored_instances:
        print_error("No instances found in session")
        return []

    console.print(
        f"  [af.primary]Checking {len(stored_instances)} "
        f"{TERMS['instances'].lower()}...[/af.primary]"
    )
    console.print()

    live: list[InstanceInfo] = []
    lost = 0

    for info in stored_instances:
        display = PROVIDER_DISPLAY.get(info.provider, info.provider.value)
        label = info.name or info.instance_id

        try:
            provider = get_provider(info.provider, config.api_keys[info.provider])
            current = provider.get_instance(info.instance_id)

            if current.status == InstanceStatus.RUNNING and current.ssh:
                console.print(
                    f"  [af.success]{label} [{display}] already running "
                    f"@ {current.ssh.host}:{current.ssh.port}[/af.success]"
                )
                store.update_instance_ssh(info.instance_id, current.ssh)
                live.append(current)

            elif current.status in (InstanceStatus.STOPPED, InstanceStatus.PENDING):
                if not hasattr(provider, "start_instance"):
                    print_error(
                        f"{label} [{display}] stopped but provider "
                        f"doesn't support restart"
                    )
                    lost += 1
                    continue

                console.print(
                    f"  [af.secondary]{label} [{display}] "
                    f"restarting...[/af.secondary]"
                )
                provider.start_instance(info.instance_id)
                restarted = provider.wait_until_ready(info.instance_id, timeout=300)
                console.print(
                    f"  [af.success]{label} [{display}] "
                    f"ONLINE @ {restarted.ssh.host}:{restarted.ssh.port}[/af.success]"
                )
                store.update_instance_ssh(info.instance_id, restarted.ssh)
                store.update_instance_status(info.instance_id, InstanceStatus.RUNNING)
                live.append(restarted)

            else:
                console.print(
                    f"  [af.muted]{label} [{display}] "
                    f"status: {display_status(current.status.value)} — skipping[/af.muted]"
                )
                lost += 1

        except Exception as e:
            print_error(f"{label} [{display}] unreachable: {e}")
            lost += 1

    console.print()
    if live:
        print_success(
            f"{len(live)}/{len(stored_instances)} "
            f"{TERMS['instances'].lower()} online"
        )
    if lost:
        print_error(
            f"{lost} {TERMS['instances'].lower()} lost (deleted or unreachable)"
        )
    console.print()

    return live


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
