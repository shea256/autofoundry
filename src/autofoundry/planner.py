"""GPU selection and cost optimization planner."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.prompt import Confirm, IntPrompt, Prompt

from autofoundry.config import PROVIDER_DISPLAY, Config
from autofoundry.gpu_filter import (
    GpuQuery,
    filter_by_vram,
    gpu_name_matches,
)
from autofoundry.models import GpuOffer, ProviderName, ProvisioningPlan
from autofoundry.providers import get_provider
from autofoundry.theme import (
    TERMS,
    console,
    make_table,
    print_error,
    print_header,
    print_success,
    term,
)


def _query_provider_offers(
    provider_name: ProviderName, api_key: str, gpu_type: str | None,
    datacenter_id: str | None = None,
    min_bandwidth_mbps: float = 5000.0,
    vram_min: float | None = None,
) -> tuple[ProviderName, list[GpuOffer], str | None]:
    """Query a single provider for GPU offers. Returns (provider, offers, error)."""
    try:
        provider = get_provider(provider_name, api_key, min_bandwidth_mbps=min_bandwidth_mbps)
        # Provider-specific kwargs
        if datacenter_id and provider_name == ProviderName.RUNPOD:
            offers = provider.list_gpu_offers(gpu_type, datacenter_id=datacenter_id)
        elif vram_min is not None and provider_name == ProviderName.VASTAI:
            offers = provider.list_gpu_offers(gpu_type, vram_min=vram_min)
        else:
            offers = provider.list_gpu_offers(gpu_type)
        return (provider_name, offers, None)
    except Exception as e:
        return (provider_name, [], str(e))


def query_all_offers(
    config: Config, query: GpuQuery, datacenter_id: str | None = None,
) -> list[GpuOffer]:
    """Query all configured providers for GPU offers concurrently.

    When query has a gpu_type, passes it to providers for server-side filtering.
    When query uses tier/VRAM filtering, fetches all offers and filters client-side.
    """
    # For tier-based queries, pass vram_min to providers that support
    # server-side VRAM filtering (e.g. Vast.ai) so their result limits
    # don't exclude high-VRAM GPUs.
    provider_gpu_type = query.gpu_type  # None for tier-based queries
    provider_vram_min = query.vram_min if not query.gpu_type else None

    # Collect raw results per provider
    raw_offers: dict[ProviderName, list[GpuOffer]] = {}
    provider_errors: dict[ProviderName, str] = {}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(
                _query_provider_offers, provider, config.api_keys[provider],
                provider_gpu_type, datacenter_id, config.min_bandwidth_mbps,
                provider_vram_min,
            ): provider
            for provider in config.configured_providers
        }
        for future in as_completed(futures):
            provider = futures[future]
            try:
                _, offers, error = future.result()
                if error:
                    provider_errors[provider] = error
                else:
                    raw_offers[provider] = offers
            except Exception as e:
                provider_errors[provider] = str(e)

    # Merge all offers and apply filters
    all_offers: list[GpuOffer] = []
    for offers in raw_offers.values():
        all_offers.extend(offers)

    if query.single_gpu:
        all_offers = [o for o in all_offers if o.gpu_count == 1]

    if query.vram_min is not None or query.vram_max is not None:
        all_offers = filter_by_vram(all_offers, query.vram_min, query.vram_max)

    if query.gpu_patterns:
        all_offers = [
            o for o in all_offers
            if any(gpu_name_matches(pat, o.gpu_type) for pat in query.gpu_patterns)
        ]

    if query.gpu_type:
        all_offers = [o for o in all_offers if gpu_name_matches(query.gpu_type, o.gpu_type)]

    # Report per-provider counts (after filtering)
    for provider in config.configured_providers:
        display = PROVIDER_DISPLAY.get(provider, provider.value)
        if provider in provider_errors:
            print_error(f"{display}: {provider_errors[provider]}")
        else:
            count = sum(1 for o in all_offers if o.provider == provider)
            if count:
                console.print(
                    f"  [af.success]OK:[/af.success] {display} — "
                    f"{count} {term('instances', count).lower()} found"
                )
            else:
                units = TERMS['instances'].lower()
                console.print(
                    f"  [af.muted]{display} — no matching {units}[/af.muted]"
                )

    # Sort by price ascending
    all_offers.sort(key=lambda o: o.price_per_hour)
    return all_offers


_DEFAULT_PER_PROVIDER = 10


def display_offers(offers: list[GpuOffer], *, truncate: bool = True) -> tuple[list[GpuOffer], dict]:
    """Display GPU offers grouped by provider.

    Returns (displayed_offers, truncated_providers) where truncated_providers
    maps short names to (ProviderName, by_provider_dict) for lazy expansion.
    When truncate=False, all offers are shown and truncated_providers is empty.
    """
    if not offers:
        print_error(f"No GPU {TERMS['instances'].lower()} found matching your criteria.")
        return [], {}

    from collections import defaultdict

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
    for p in by_provider:
        if p not in provider_order:
            provider_order.append(p)

    displayed: list[GpuOffer] = []
    global_num = 1
    truncated_providers: dict[str, tuple[ProviderName, dict]] = {}

    for provider in provider_order:
        all_provider_offers = by_provider[provider]
        if truncate:
            show_offers = all_provider_offers[:_DEFAULT_PER_PROVIDER]
        else:
            show_offers = all_provider_offers
        total_count = len(all_provider_offers)
        display_name = PROVIDER_DISPLAY.get(provider, provider.value)

        hidden = total_count - len(show_offers)
        title = f"{display_name} — {total_count} {term('instances', total_count).lower()}"
        if hidden > 0:
            title += f" (showing {len(show_offers)})"

        displayed, global_num = _render_provider_table(
            title, show_offers, displayed, global_num
        )

        if hidden > 0:
            short_name = display_name.lower().split()[0]
            truncated_providers[short_name] = (provider, by_provider)
            console.print(
                f"  [af.muted]{hidden} more — type '{short_name}' to expand[/af.muted]"
            )

    console.print()
    return displayed, truncated_providers


def expand_provider(
    key: str,
    truncated_providers: dict,
    displayed: list[GpuOffer],
) -> list[GpuOffer]:
    """Expand a truncated provider's remaining offers. Mutates truncated_providers and displayed."""
    provider, by_provider = truncated_providers.pop(key)
    all_provider_offers = by_provider[provider]
    remaining = all_provider_offers[_DEFAULT_PER_PROVIDER:]
    display_name = PROVIDER_DISPLAY.get(provider, provider.value)

    global_num = len(displayed) + 1
    displayed, _ = _render_provider_table(
        f"{display_name} — remaining {len(remaining)} {term('instances', len(remaining)).lower()}",
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
    query: GpuQuery,
    total_experiments: int,
    script_path: str,
    provider_filter: str | None = None,
    region_filter: str | None = None,
    datacenter_id: str | None = None,
) -> ProvisioningPlan | None:
    """Non-interactive planning: auto-select cheapest matching offer."""
    print_header(TERMS["planning"])
    console.print()
    desc = query.description
    console.print(f"  [af.muted]Querying supply lines for {desc} availability...[/af.muted]")

    offers = query_all_offers(config, query, datacenter_id=datacenter_id)
    if not offers:
        print_error(f"No offers found for {query.description}.")
        return None

    # Filter by provider
    if provider_filter:
        pf = provider_filter.lower()
        offers = [o for o in offers if pf in o.provider.value.lower()]
        if not offers:
            print_error(f"No {query.description} offers from provider '{provider_filter}'.")
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
            # If offer region is a RunPod cloud type (secure/community),
            # treat --region as an explicit cloud-type filter.
            if o.region and o.region.lower() in _NON_GEOGRAPHIC_REGIONS:
                return o.region.lower() == rf

            # Offers without any region metadata always pass
            if not o.region:
                return True

            # Geographic region match (e.g. US, EU)
            if rf in o.region.lower():
                return True

            # Datacenter ID match as fallback
            dc = o.metadata.get("data_center_id", "")
            return bool(dc and rf in dc.lower())

        filtered = [o for o in offers if _region_match(o)]
        if not filtered:
            regions = sorted({
                o.region or o.metadata.get("data_center_id", "?")
                for o in offers
            })
            print_error(
                f"No {query.description} offers matching region '{region_filter}'.\n"
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
        f"{total_experiments} {term('experiments', total_experiments).lower()}, "
        f"${cheapest.price_per_hour:.2f}/hr"
    )
    console.print()

    return plan


def interactive_plan(
    config: Config,
    query: GpuQuery,
    total_experiments: int,
    script_path: str,
    provider_filter: str | None = None,
    region_filter: str | None = None,
    datacenter_id: str | None = None,
) -> ProvisioningPlan | None:
    """Full interactive planning flow: query, display, recommend, confirm."""
    print_header(TERMS["planning"])
    console.print()
    desc = query.description
    if datacenter_id:
        console.print(
            f"  [af.muted]Querying supply lines for {desc} in {datacenter_id}...[/af.muted]"
        )
    else:
        console.print(f"  [af.muted]Querying supply lines for {desc} availability...[/af.muted]")

    offers = query_all_offers(config, query, datacenter_id=datacenter_id)

    # Apply provider/region filters (e.g. when a volume constrains the choice)
    if provider_filter:
        pf = provider_filter.lower()
        offers = [o for o in offers if o.provider.value == pf]
    if region_filter:
        rf = region_filter.lower()
        offers = [o for o in offers if o.region and rf in o.region.lower()]
    displayed, truncated = display_offers(offers)

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
        if not selections:
            pick = Prompt.ask(
                f"  [af.label]Select {TERMS['instance'].lower()} #[/af.label]",
                default="1",
            )
        else:
            # Show current plan and ask to confirm or add more
            total_instances = sum(c for _, c in selections)
            cost = sum(o.price_per_hour * c for o, c in selections)
            console.print(
                f"  [af.primary]DEPLOYMENT PLAN:[/af.primary] "
                f"{total_instances} {term('instances', total_instances).lower()}, "
                f"{total_experiments} {term('experiments', total_experiments).lower()}, "
                f"${cost:.2f}/hr"
            )
            pick = Prompt.ask(
                "  [af.label]Confirm?[/af.label] "
                "[af.muted](y/Enter to deploy, + to add more, n to cancel)[/af.muted]",
                default="y",
            )
            stripped = pick.strip().lower()
            if stripped in ("y", ""):
                break
            if stripped == "n":
                console.print("  [af.muted]Deployment cancelled.[/af.muted]")
                return None
            if stripped == "+":
                # Go back to selection prompt
                pick = Prompt.ask(
                    f"  [af.label]Select {TERMS['instance'].lower()} #[/af.label]",
                )
            else:
                print_error("Enter y, +, or n")
                continue

        # Check if user typed a provider name to expand truncated results
        pick_lower = pick.strip().lower()
        if pick_lower in truncated:
            offers = expand_provider(pick_lower, truncated, offers)
            continue

        try:
            idx = int(pick) - 1
            if idx < 0 or idx >= len(offers):
                print_error(f"Invalid selection. Choose 1-{len(offers)}")
                continue
        except ValueError:
            print_error("Enter a number or provider name to expand")
            continue

        selected = offers[idx]
        if selected.availability == 0:
            console.print(
                f"  [af.alert]WARNING:[/af.alert] This unit shows 0 availability — "
                f"launch will likely fail."
            )
            if not Confirm.ask("  [af.label]Continue anyway?[/af.label]", default=False):
                continue

        # For multi-experiment runs, ask how many; otherwise default to 1
        if total_experiments > 1:
            count = IntPrompt.ask(
                f"  [af.label]How many {TERMS['instances'].lower()} of this type?[/af.label]",
                default=1,
            )
        else:
            count = 1

        selections.append((selected, count))

    if not selections:
        if recommendation:
            selections = recommendation
        else:
            print_error("No instances selected.")
            return None

    return ProvisioningPlan(
        offers=selections,
        total_experiments=total_experiments,
        script_path=script_path,
    )
