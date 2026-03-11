"""GPU selection and cost optimization planner."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.prompt import Confirm, IntPrompt, Prompt

from autofoundry.config import PROVIDER_DISPLAY, Config
from autofoundry.models import GpuOffer, ProviderName, ProvisioningPlan
from autofoundry.providers import get_provider
from autofoundry.theme import (
    TERMS,
    console,
    make_table,
    print_error,
    print_header,
    print_success,
)


def _query_provider_offers(
    provider_name: ProviderName, api_key: str, gpu_type: str
) -> tuple[ProviderName, list[GpuOffer], str | None]:
    """Query a single provider for GPU offers. Returns (provider, offers, error)."""
    try:
        provider = get_provider(provider_name, api_key)
        offers = provider.list_gpu_offers(gpu_type)
        return (provider_name, offers, None)
    except Exception as e:
        return (provider_name, [], str(e))


def query_all_offers(config: Config, gpu_type: str) -> list[GpuOffer]:
    """Query all configured providers for GPU offers concurrently."""
    all_offers: list[GpuOffer] = []

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                _query_provider_offers, provider, config.api_keys[provider], gpu_type
            ): provider
            for provider in config.configured_providers
        }
        for future in as_completed(futures):
            provider = futures[future]
            display = PROVIDER_DISPLAY.get(provider, provider.value)
            try:
                _, offers, error = future.result()
                if error:
                    print_error(f"{display}: {error}")
                elif offers:
                    console.print(
                        f"  [af.success]OK:[/af.success] {display} — "
                        f"{len(offers)} offers found"
                    )
                else:
                    console.print(
                        f"  [af.muted]{display} — no {gpu_type} offers[/af.muted]"
                    )
                all_offers.extend(offers)
            except Exception as e:
                print_error(f"{display} query failed: {e}")

    # Sort by price ascending
    all_offers.sort(key=lambda o: o.price_per_hour)
    return all_offers


def display_offers(offers: list[GpuOffer]) -> list[GpuOffer]:
    """Display GPU offers grouped by provider. Returns the displayed offers list (for selection by #)."""
    if not offers:
        print_error("No GPU offers found matching your criteria.")
        return []

    from collections import defaultdict

    MAX_PER_PROVIDER = 50

    by_provider: dict[ProviderName, list[GpuOffer]] = defaultdict(list)
    for offer in offers:
        by_provider[offer.provider].append(offer)

    # Display order: providers sorted by their cheapest offer
    provider_order = sorted(
        by_provider.keys(),
        key=lambda p: by_provider[p][0].price_per_hour if by_provider[p] else float("inf"),
    )

    displayed: list[GpuOffer] = []
    global_num = 1

    for provider in provider_order:
        provider_offers = by_provider[provider][:MAX_PER_PROVIDER]
        display_name = PROVIDER_DISPLAY.get(provider, provider.value)

        table = make_table(
            f"{display_name} — {len(provider_offers)} {TERMS['offers'].lower()}",
            [
                ("#", "af.muted"),
                ("GPU", ""),
                ("VRAM (GB)", ""),
                ("$/hr", "af.success"),
                ("DL (Mbps)", "af.muted"),
                ("Region", "af.muted"),
                ("Avail", ""),
            ],
        )

        for offer in provider_offers:
            dl_speed = f"{offer.inet_down_mbps:.0f}" if offer.inet_down_mbps > 0 else "—"
            # Show GPU count prefix (e.g. "2x H100 SXM") when > 1,
            # but skip if already in the name (Lambda Labs includes it)
            gpu_label = offer.gpu_type
            if offer.gpu_count > 1 and not gpu_label.startswith(f"{offer.gpu_count}x"):
                gpu_label = f"{offer.gpu_count}x {gpu_label}"
            table.add_row(
                str(global_num),
                gpu_label,
                f"{offer.gpu_ram_gb:.0f}",
                f"${offer.price_per_hour:.2f}",
                dl_speed,
                offer.region or "—",
                str(offer.availability) if offer.availability > 0 else "—",
            )
            displayed.append(offer)
            global_num += 1

        console.print()
        console.print(table)

    console.print()
    return displayed


def recommend_plan(
    offers: list[GpuOffer], total_experiments: int
) -> list[tuple[GpuOffer, int]]:
    """Recommend a distribution plan using the cheapest offers."""
    if not offers:
        return []

    # Default: use 1 instance from the cheapest offer
    # User can adjust in the interactive flow
    cheapest = offers[0]
    return [(cheapest, 1)]


def interactive_plan(
    config: Config, gpu_type: str, total_experiments: int, script_path: str
) -> ProvisioningPlan | None:
    """Full interactive planning flow: query, display, recommend, confirm."""
    print_header(TERMS["planning"])
    console.print()
    console.print(f"  [af.muted]Querying supply lines for {gpu_type} availability...[/af.muted]")

    offers = query_all_offers(config, gpu_type)
    displayed = display_offers(offers)

    if not displayed:
        return None

    # Use displayed list for selection (matches the # shown in tables)
    offers = displayed

    # Show recommendation
    recommendation = recommend_plan(offers, total_experiments)
    if recommendation:
        offer, count = recommendation[0]
        display = PROVIDER_DISPLAY.get(offer.provider, offer.provider.value)
        console.print(
            f"  [af.primary]Recommended:[/af.primary] "
            f"{count}x {offer.gpu_type} on {display} "
            f"@ ${offer.price_per_hour:.2f}/hr"
        )
        console.print()

    # Let user select
    selections: list[tuple[GpuOffer, int]] = []

    while True:
        pick = Prompt.ask(
            "  [af.label]Select offer # (or 'done' to confirm)[/af.label]",
            default="1" if not selections else "done",
        )

        if pick.lower() == "done":
            if not selections:
                # Use recommendation as default
                selections = recommendation
            break

        try:
            idx = int(pick) - 1
            if idx < 0 or idx >= len(offers):
                print_error(f"Invalid selection. Choose 1-{len(offers)}")
                continue
        except ValueError:
            print_error("Enter a number or 'done'")
            continue

        count = IntPrompt.ask(
            f"  [af.label]How many {TERMS['instances'].lower()} of this type?[/af.label]",
            default=1,
        )
        selections.append((offers[idx], count))

        total_instances = sum(c for _, c in selections)
        cost = sum(o.price_per_hour * c for o, c in selections)
        print_success(
            f"Selected {total_instances} {TERMS['instances'].lower()} "
            f"(${cost:.2f}/hr total)"
        )
        console.print()

    if not selections:
        print_error("No instances selected.")
        return None

    # Confirm
    plan = ProvisioningPlan(
        offers=selections,
        total_experiments=total_experiments,
        script_path=script_path,
    )

    total_instances = plan.total_instances
    cost = plan.estimated_cost_per_hour
    console.print()
    console.print(
        f"  [af.primary]DEPLOYMENT PLAN:[/af.primary] "
        f"{total_instances} {TERMS['instances'].lower()}, "
        f"{total_experiments} {TERMS['experiments'].lower()}, "
        f"${cost:.2f}/hr"
    )

    if not Confirm.ask("  [af.label]Confirm deployment?[/af.label]", default=True):
        console.print("  [af.muted]Deployment cancelled.[/af.muted]")
        return None

    return plan
