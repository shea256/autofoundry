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
                        f"{len(offers)} {TERMS['instances'].lower()} found"
                    )
                else:
                    console.print(
                        f"  [af.muted]{display} — no {gpu_type} {TERMS['instances'].lower()}[/af.muted]"
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
        print_error(f"No GPU {TERMS['instances'].lower()} found matching your criteria.")
        return []

    from collections import defaultdict

    from rich.prompt import Prompt

    INITIAL_PER_PROVIDER = 10

    by_provider: dict[ProviderName, list[GpuOffer]] = defaultdict(list)
    for offer in offers:
        by_provider[offer.provider].append(offer)

    # Fixed display order: RunPod, Lambda Labs, Vast.ai, PRIME Intellect
    _PROVIDER_DISPLAY_ORDER = [
        ProviderName.RUNPOD,
        ProviderName.LAMBDALABS,
        ProviderName.VASTAI,
        ProviderName.PRIMEINTELLECT,
    ]
    provider_order = [p for p in _PROVIDER_DISPLAY_ORDER if p in by_provider]
    # Append any unknown providers at the end
    for p in by_provider:
        if p not in provider_order:
            provider_order.append(p)

    displayed: list[GpuOffer] = []
    global_num = 1
    truncated_providers: dict[str, tuple[ProviderName, int]] = {}

    for provider in provider_order:
        all_provider_offers = by_provider[provider]
        show_offers = all_provider_offers[:INITIAL_PER_PROVIDER]
        total_count = len(all_provider_offers)
        display_name = PROVIDER_DISPLAY.get(provider, provider.value)

        hidden = total_count - len(show_offers)
        title = f"{display_name} — {total_count} {TERMS['instances'].lower()}"
        if hidden > 0:
            title += f" (showing {len(show_offers)})"

        displayed, global_num = _render_provider_table(
            title, show_offers, displayed, global_num
        )

        if hidden > 0:
            short_name = display_name.lower().split()[0]
            truncated_providers[short_name] = (provider, total_count)
            console.print(
                f"  [af.muted]{hidden} more — type [/af.muted]"
                f"[af.primary]{short_name}[/af.primary]"
                f"[af.muted] to see all[/af.muted]"
            )

    console.print()

    # Let the user expand truncated providers
    while truncated_providers:
        choice = Prompt.ask(
            "  [af.label]Expand a provider (or Enter to continue)[/af.label]",
            default="",
        )
        if not choice.strip():
            break
        key = choice.strip().lower()
        if key not in truncated_providers:
            console.print(f"  [af.muted]Unknown provider. Options: {', '.join(truncated_providers)}[/af.muted]")
            continue

        provider, _ = truncated_providers.pop(key)
        all_provider_offers = by_provider[provider]
        remaining = all_provider_offers[INITIAL_PER_PROVIDER:]
        display_name = PROVIDER_DISPLAY.get(provider, provider.value)

        displayed, global_num = _render_provider_table(
            f"{display_name} — remaining {len(remaining)} {TERMS['instances'].lower()}",
            remaining, displayed, global_num,
        )
        console.print()

    return displayed


def _render_provider_table(
    title: str,
    offers: list[GpuOffer],
    displayed: list[GpuOffer],
    global_num: int,
) -> tuple[list[GpuOffer], int]:
    """Render a provider table and append offers to the displayed list."""
    table = make_table(
        title,
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

    for offer in offers:
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
    return displayed, global_num


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


def auto_plan(
    config: Config,
    gpu_type: str,
    total_experiments: int,
    script_path: str,
    provider_filter: str | None = None,
    region_filter: str | None = None,
) -> ProvisioningPlan | None:
    """Non-interactive planning: auto-select cheapest matching offer."""
    print_header(TERMS["planning"])
    console.print()
    console.print(f"  [af.muted]Querying supply lines for {gpu_type} availability...[/af.muted]")

    offers = query_all_offers(config, gpu_type)
    if not offers:
        print_error(f"No {gpu_type} offers found.")
        return None

    # Filter by provider
    if provider_filter:
        pf = provider_filter.lower()
        offers = [o for o in offers if pf in o.provider.value.lower()]
        if not offers:
            print_error(f"No {gpu_type} offers from provider '{provider_filter}'.")
            return None

    # Filter by region (also check metadata.data_center_id)
    # Some providers (e.g. RunPod) don't expose geographic region in offers —
    # their "region" field is a cloud type like SECURE/COMMUNITY.  These offers
    # always pass the geographic region filter; the datacenter is selected at
    # pod creation time.
    if region_filter:
        rf = region_filter.lower()
        _NON_GEOGRAPHIC_REGIONS = {"secure", "community"}

        def _region_match(o: GpuOffer) -> bool:
            # Offers without geographic regions always pass
            if o.region and o.region.lower() in _NON_GEOGRAPHIC_REGIONS:
                return True
            if not o.region:
                return True
            if rf in o.region.lower():
                return True
            dc = o.metadata.get("data_center_id", "")
            return bool(dc and rf in dc.lower())

        filtered = [o for o in offers if _region_match(o)]
        if not filtered:
            regions = sorted({
                o.region or o.metadata.get("data_center_id", "?")
                for o in offers
            })
            print_error(
                f"No {gpu_type} offers matching region '{region_filter}'.\n"
                f"  Available regions: {', '.join(regions)}"
            )
            return None
        offers = filtered

    # Already sorted by price — pick cheapest
    cheapest = offers[0]
    display = PROVIDER_DISPLAY.get(cheapest.provider, cheapest.provider.value)
    region_label = f" ({cheapest.region})" if cheapest.region else ""
    console.print(
        f"  [af.primary]Auto-selected:[/af.primary] "
        f"{cheapest.gpu_type} on {display}{region_label} "
        f"@ ${cheapest.price_per_hour:.2f}/hr"
    )

    plan = ProvisioningPlan(
        offers=[(cheapest, 1)],
        total_experiments=total_experiments,
        script_path=script_path,
    )

    console.print(
        f"  [af.primary]DEPLOYMENT PLAN:[/af.primary] "
        f"1 {TERMS['instance'].lower()}, "
        f"{total_experiments} {TERMS['experiment'].lower()}, "
        f"${cheapest.price_per_hour:.2f}/hr"
    )
    console.print()

    return plan


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
            f"  [af.label]Select {TERMS['instance'].lower()} # (or 'done' to confirm)[/af.label]",
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

        selected = offers[idx]
        if selected.availability == 0:
            console.print(
                f"  [af.alert]WARNING:[/af.alert] This unit shows 0 availability — "
                f"launch will likely fail."
            )
            if not Confirm.ask("  [af.label]Continue anyway?[/af.label]", default=False):
                continue

        count = IntPrompt.ask(
            f"  [af.label]How many {TERMS['instances'].lower()} of this type?[/af.label]",
            default=1,
        )
        selections.append((selected, count))

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
