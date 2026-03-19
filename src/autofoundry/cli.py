"""Main CLI entry point for autofoundry."""

from __future__ import annotations

import os
from pathlib import Path

import click
import typer
from dotenv import load_dotenv
from rich.prompt import IntPrompt, Prompt

from autofoundry import __version__
from autofoundry.config import Config, first_run_setup
from autofoundry.gpu_filter import (
    DEFAULT_MIN_VRAM,
    DEFAULT_SEGMENT,
    GPU_TIERS,
    GpuQuery,
    resolve_query,
)
from autofoundry.models import Session, SessionStatus
from autofoundry.state import SessionStore
from autofoundry.theme import (
    TERMS,
    console,
    display_status,
    print_banner,
    print_error,
    print_header,
    print_status,
    print_success,
    term,
)

load_dotenv()  # load .env into os.environ (e.g. HF_TOKEN for authenticated HF Hub requests)

app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    invoke_without_command=True,
)


@app.callback(context_settings={"help_option_names": []})
def _default(
    ctx: typer.Context,
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
) -> None:
    """Run ML experiments across GPU clouds."""
    if help_ or ctx.invoked_subcommand is None:
        print_banner(version=__version__)
        console.print()
        console.print("  [af.muted]COMMANDS:[/af.muted]")
        console.print("    [af.secondary]config[/af.secondary]    Configure API keys, SSH key, and default GPU type")
        console.print("    [af.secondary]inventory[/af.secondary] Browse GPU inventory across supply lines")
        console.print("    [af.secondary]volumes[/af.secondary]   Manage network volumes (list, create)")
        console.print("    [af.secondary]run[/af.secondary]       Launch GPU experiment orchestration engine")
        console.print("    [af.secondary]status[/af.secondary]    Show status of operations and instances")
        console.print("    [af.secondary]results[/af.secondary]   View experiment results and metrics")
        console.print("    [af.secondary]teardown[/af.secondary]  Terminate all instances for an operation")
        console.print()
        console.print("  [af.muted]Run[/af.muted] [af.primary]autofoundry <command> --help[/af.primary] [af.muted]for details.[/af.muted]")
        console.print()
        if help_:
            raise typer.Exit()


def _load_or_setup_config() -> Config:
    """Load existing config or run first-time setup."""
    config = Config.load()
    if config is None:
        return first_run_setup()
    return config


def _resolve_script(script_arg: str | None, config: Config) -> str:
    """Resolve the script path from CLI arg, last-used, or interactive prompt."""
    # Try CLI argument first
    if script_arg:
        path = Path(script_arg).expanduser().resolve()
        if path.exists() and path.is_file():
            return str(path)
        print_error(f"File not found: {path}")
        raise SystemExit(1)

    # Try last-used script as default, fall back to bundled example
    default_abs = config.last_script if config.last_script else ""
    if default_abs:
        # Show as relative path if under cwd, otherwise absolute
        try:
            default = str(Path(default_abs).relative_to(Path.cwd()))
        except ValueError:
            default = default_abs
        # Only use as default if the file still exists
        if not Path(default_abs).exists():
            default = ""

    if not default:
        # Fall back to scripts/run_autoresearch.sh relative to cwd
        fallback = Path.cwd() / "scripts" / "run_autoresearch.sh"
        if fallback.exists():
            default = "scripts/run_autoresearch.sh"

    while True:
        prompt_text = "  [af.label]Script path[/af.label]"
        if default:
            script_path = Prompt.ask(prompt_text, default=default)
        else:
            script_path = Prompt.ask(prompt_text)
        path = Path(script_path).expanduser().resolve()
        if path.exists() and path.is_file():
            return str(path)
        print_error(f"File not found: {path}")


def _prompt_session_params(
    config: Config, script_arg: str | None = None
) -> tuple[str, int, GpuQuery]:
    """Prompt user for script path, experiment count, and GPU tier/type."""
    print_header(f"{TERMS['experiment']} CONFIGURATION")
    console.print()

    # Script path
    script_path = _resolve_script(script_arg, config)
    console.print()

    # Number of experiments
    num_experiments = IntPrompt.ask(
        f"  [af.label]Number of {TERMS['experiments'].lower()}[/af.label]",
        default=1,
    )
    console.print()

    # GPU tier selection
    gpu_query = _prompt_tier_selection(config.default_segment, config.default_min_vram)

    return script_path, num_experiments, gpu_query


def _prompt_tier_selection(
    default_segment: str = DEFAULT_SEGMENT,
    default_min_vram: float | None = DEFAULT_MIN_VRAM,
) -> GpuQuery:
    """Prompt user to select a GPU tier interactively.

    Shows numbered tier options grouped by category.
    """
    # Find the default tier index by matching segment + vram_min
    default_idx = 0
    for i, tier in enumerate(GPU_TIERS):
        if (
            tier.category == default_segment
            and default_min_vram is not None
            and tier.vram_min <= default_min_vram < tier.vram_max
        ):
            default_idx = i + 1

    console.print("  [af.label]GPU tier[/af.label]")
    current_category = ""
    for i, tier in enumerate(GPU_TIERS):
        if tier.category != current_category:
            current_category = tier.category
            console.print(f"    [af.secondary]{current_category.title()}[/af.secondary]")
        marker = " [af.primary](default)[/af.primary]" if i + 1 == default_idx else ""
        console.print(f"      [af.muted]{i + 1}.[/af.muted] {tier.label}{marker}")

    console.print()
    console.print("    [af.muted]Or type a GPU name (e.g. H100)[/af.muted]")

    pick = Prompt.ask(
        "  [af.label]Select tier #[/af.label]",
        default=str(default_idx),
    )

    try:
        idx = int(pick) - 1
        if 0 <= idx < len(GPU_TIERS):
            selected = GPU_TIERS[idx]
            return resolve_query(
                segment=selected.category,
                vram_min=selected.vram_min,
                vram_max=selected.vram_max,
            )
    except ValueError:
        pass

    # Fallback: treat as GPU name
    return resolve_query(gpu_type=pick)


def _show_session_summary(session: Session) -> None:
    """Display session configuration summary."""
    console.print()
    print_status(TERMS["session"], session.session_id)
    print_status("Script", session.script_path)
    print_status(term("experiments", session.total_experiments), str(session.total_experiments))
    print_status("GPU", session.gpu_type)
    console.print()


@app.command(context_settings={"help_option_names": []})
def config(
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
) -> None:
    """Configure API keys, SSH key, and default GPU type."""
    if help_:
        _print_command_help("autofoundry config", "Configure API keys, SSH key, and default GPU type", [
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()
    existing = Config.load()
    first_run_setup(existing)


def _get_volume_eligible_provider(
    config: Config, plan_providers: set | None = None,
) -> tuple:
    """Return (provider_name, provider) for the first volume-capable provider.

    If plan_providers is given, only considers those providers.
    Otherwise uses all configured providers.
    Returns (None, None) if no eligible provider exists.
    """
    from autofoundry.models import ProviderName
    from autofoundry.providers import get_provider

    VOLUME_PROVIDERS = {ProviderName.RUNPOD, ProviderName.LAMBDALABS}
    candidates = plan_providers if plan_providers is not None else set(config.configured_providers)
    eligible = candidates & VOLUME_PROVIDERS

    if not eligible:
        return None, None

    provider_name = next(iter(eligible))
    provider = get_provider(provider_name, config.api_keys[provider_name])

    if not hasattr(provider, "list_volumes"):
        return None, None

    return provider_name, provider


def _create_volume_interactive(
    provider_name, provider, volume_name: str | None = None,
) -> str:
    """Prompt for volume details and create it. Returns volume_id or empty string."""
    from autofoundry.models import ProviderName

    from rich.prompt import Confirm as RichConfirm

    if not volume_name:
        volume_name = Prompt.ask("  [af.label]Volume name[/af.label]")
        if not volume_name.strip():
            return ""

    if provider_name == ProviderName.RUNPOD:
        size_gb = IntPrompt.ask(
            "  [af.label]Volume size (GB)[/af.label]",
            default=100,
        )
        region = Prompt.ask(
            "  [af.label]Data center ID[/af.label]",
            default="US-TX-3",
        )
        if not RichConfirm.ask(
            f"  [af.label]Create {size_gb}GB volume '{volume_name}' in {region}?[/af.label]",
            default=True,
        ):
            return ""
        vol = provider.create_volume(volume_name, size_gb, region)
    elif provider_name == ProviderName.LAMBDALABS:
        region = Prompt.ask(
            "  [af.label]Region[/af.label]",
            default="us-east-1",
        )
        if not RichConfirm.ask(
            f"  [af.label]Create volume '{volume_name}' in {region}?[/af.label]",
            default=True,
        ):
            return ""
        vol = provider.create_volume(volume_name, region)
    else:
        return ""

    print_success(f"Volume created: {vol.name} ({vol.volume_id})")
    print_status("Mount path", vol.mount_path)
    return vol.volume_id


def _resolve_volume(
    config: Config, volume_name: str, plan_providers: set | None = None,
) -> tuple[str, str, str]:
    """Resolve a volume name to a volume ID, creating if necessary.

    Returns (volume_id, volume_region, provider_name_value), or ("", "", "").
    """
    provider_name, provider = _get_volume_eligible_provider(config, plan_providers)

    if provider_name is None:
        print_error("No configured providers support network volumes (RunPod, Lambda Labs)")
        return "", "", ""

    pname = provider_name.value

    # Check for existing volume with this name
    console.print(f"  [af.muted]Checking for volume '{volume_name}'...[/af.muted]")
    volumes = provider.list_volumes()
    for vol in volumes:
        if vol.name == volume_name:
            print_success(f"Found volume: {vol.name} ({vol.size_gb}GB, {vol.region})")
            print_status("Mount path", vol.mount_path)
            return vol.volume_id, vol.region, pname

    # Volume doesn't exist — create it
    console.print(f"  [af.muted]Volume '{volume_name}' not found. Creating...[/af.muted]")
    console.print()
    vid = _create_volume_interactive(provider_name, provider, volume_name)
    # Re-fetch to get region of newly created volume
    if vid:
        for vol in provider.list_volumes():
            if vol.volume_id == vid:
                return vid, vol.region, pname
    return vid, "", pname


def _interactive_volume_prompt(
    config: Config, plan_providers: set | None = None,
) -> tuple[str, str, str]:
    """Prompt user to attach a volume (interactive mode).

    Queries all volume-capable providers and shows volumes in a single list.
    Returns (volume_id, volume_region, provider_name_value), or ("", "", "").
    """
    from autofoundry.config import PROVIDER_DISPLAY
    from autofoundry.models import ProviderName
    from autofoundry.providers import get_provider
    from autofoundry.theme import make_table

    VOLUME_PROVIDERS = {ProviderName.RUNPOD, ProviderName.LAMBDALABS}
    candidates = plan_providers if plan_providers is not None else set(config.configured_providers)
    eligible = sorted(candidates & VOLUME_PROVIDERS, key=lambda p: p.value)

    if not eligible:
        return "", "", ""

    # Gather volumes from all eligible providers
    all_volumes: list[tuple] = []  # (VolumeInfo, provider_name, provider_instance)
    providers_map = {}
    for pname in eligible:
        prov = get_provider(pname, config.api_keys[pname])
        if not hasattr(prov, "list_volumes"):
            continue
        providers_map[pname] = prov
        try:
            for vol in prov.list_volumes():
                all_volumes.append((vol, pname, prov))
        except Exception as e:
            print_error(f"Could not list volumes on {PROVIDER_DISPLAY.get(pname, pname.value)}: {e}")

    console.print()
    print_header("NETWORK VOLUMES")
    console.print()

    if all_volumes:
        table = make_table(f"{len(all_volumes)} volume(s)", [
            ("#", "af.muted"),
            ("Provider", "af.secondary"),
            ("Name", "af.primary"),
            ("Size", ""),
            ("Region", ""),
            ("Mount Path", "af.muted"),
        ])
        for i, (vol, pname, _prov) in enumerate(all_volumes, 1):
            table.add_row(
                str(i),
                PROVIDER_DISPLAY.get(pname, pname.value),
                vol.name,
                f"{vol.size_gb}GB",
                vol.region or "—",
                vol.mount_path,
            )
        console.print(table)
        console.print()

        pick = Prompt.ask(
            "  [af.label]Attach a volume?[/af.label] "
            "[af.muted](# to select, 'new' to create, Enter to skip)[/af.muted]",
            default="",
        )

        if not pick.strip():
            return "", "", ""

        if pick.strip().lower() == "new":
            # Pick which provider to create on
            if len(providers_map) == 1:
                create_pname = next(iter(providers_map))
            else:
                choice = Prompt.ask(
                    "  [af.label]Provider[/af.label]",
                    choices=[p.value for p in providers_map],
                )
                create_pname = ProviderName(choice)
            create_prov = providers_map[create_pname]
            vid = _create_volume_interactive(create_pname, create_prov)
            if vid:
                for vol in create_prov.list_volumes():
                    if vol.volume_id == vid:
                        return vid, vol.region, create_pname.value
            return vid, "", create_pname.value

        try:
            idx = int(pick) - 1
            if 0 <= idx < len(all_volumes):
                vol, pname, _prov = all_volumes[idx]
                print_success(f"Attaching volume: {vol.name} ({vol.size_gb}GB, {vol.region})")
                print_status("Mount path", vol.mount_path)
                return vol.volume_id, vol.region, pname.value
            else:
                print_error(f"Invalid selection. Choose 1-{len(all_volumes)}")
                return "", "", ""
        except ValueError:
            print_error("Invalid input")
            return "", "", ""
    else:
        providers_str = ", ".join(PROVIDER_DISPLAY.get(p, p.value) for p in eligible)
        console.print(f"  [af.muted]No volumes found on {providers_str}.[/af.muted]")
        console.print()

        from rich.prompt import Confirm as RichConfirm

        if RichConfirm.ask(
            "  [af.label]Create a new volume?[/af.label]",
            default=False,
        ):
            if len(providers_map) == 1:
                create_pname = next(iter(providers_map))
            else:
                choice = Prompt.ask(
                    "  [af.label]Provider[/af.label]",
                    choices=[p.value for p in providers_map],
                )
                create_pname = ProviderName(choice)
            create_prov = providers_map[create_pname]
            vid = _create_volume_interactive(create_pname, create_prov)
            if vid:
                for vol in create_prov.list_volumes():
                    if vol.volume_id == vid:
                        return vid, vol.region, create_pname.value
            return vid, "", create_pname.value
        return "", "", ""


def _print_command_help(command: str, description: str, options: list[tuple[str, str]]) -> None:
    """Print themed help for a command."""
    print_banner(version=__version__)
    console.print()
    console.print(f"  [af.primary]{command}[/af.primary] — [af.muted]{description}[/af.muted]")
    console.print()
    console.print("  [af.muted]OPTIONS:[/af.muted]")
    for flags, desc in options:
        console.print(f"    [af.secondary]{flags:<24}[/af.secondary] {desc}")
    console.print()


@app.command(context_settings={"help_option_names": []})
def run(
    ctx: typer.Context,
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
    script: str = typer.Argument(None, help="Path to the script to run on GPU instances"),
    resume: str = typer.Option(None, "--resume", "-r", help="Resume a previous operation"),
    num: int = typer.Option(None, "--num", "-n", help="Number of experiment runs"),
    gpu: str = typer.Option(None, "--gpu", "-g", help="GPU type (e.g. H100)"),
    segment: str = typer.Option(None, "--segment", "-s", help="GPU segment (consumer, workstation, datacenter)"),
    min_vram: float = typer.Option(None, "--min-vram", help="Minimum VRAM in GB (e.g. 80)"),
    max_vram: float = typer.Option(None, "--max-vram", help="Maximum VRAM in GB"),
    volume: str = typer.Option(None, "--volume", "-v", help="Network volume name (creates if needed)"),
    provider: str = typer.Option(None, "--provider", "-p", help="Provider filter (e.g. primeintellect, vastai)"),
    region: str = typer.Option(None, "--region", help="Region filter (e.g. US, EU)"),
    image: str = typer.Option(None, "--image", "-i", help="Docker image override (e.g. runpod/autoresearch:latest)"),
    multi_gpu: bool = typer.Option(False, "--multi-gpu", help="Include multi-GPU instances"),
    auto: bool = typer.Option(False, "--auto", help="Auto-select cheapest offer, no prompts"),
) -> None:
    """Launch autofoundry — GPU experiment orchestration engine."""
    if help_:
        _print_command_help("autofoundry run", "GPU experiment orchestration engine", [
            ("[SCRIPT]", "Path to the script to run on GPU instances"),
            ("--resume, -r TEXT", "Resume a previous operation"),
            ("--num, -n INTEGER", "Number of experiment runs"),
            ("--gpu, -g TEXT", "GPU type (e.g. H100)"),
            ("--segment, -s TEXT", "GPU segment (consumer, workstation, datacenter)"),
            ("--min-vram FLOAT", "Minimum VRAM in GB (e.g. 80)"),
            ("--max-vram FLOAT", "Maximum VRAM in GB"),
            ("--volume, -v TEXT", "Network volume name (creates if needed)"),
            ("--provider, -p TEXT", "Provider filter (e.g. primeintellect, vastai)"),
            ("--region TEXT", "Region filter (e.g. US, EU, secure, community)"),
            ("--image, -i TEXT", "Docker image override (e.g. runpod/autoresearch:latest)"),
            ("--multi-gpu", "Include multi-GPU instances"),
            ("--auto", "Auto-select cheapest offer, no prompts"),
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()

    print_banner(version=__version__)

    config = _load_or_setup_config()

    # Show configured providers
    from autofoundry.config import PROVIDER_DISPLAY

    providers_str = ", ".join(PROVIDER_DISPLAY[p] for p in config.configured_providers)
    print_status("Supply lines", providers_str)
    console.print()

    if resume:
        # Resume existing session
        existing = SessionStore.list_sessions()
        if resume not in existing:
            print_error(f"Operation '{resume}' not found")
            print_status("Available", ", ".join(existing) if existing else "(none)")
            raise typer.Exit(1)
        store = SessionStore(resume)
        session = store.get_session()
        if session is None:
            print_error(f"Could not load operation '{resume}'")
            raise typer.Exit(1)
        print_success(f"Resuming {TERMS['session']} {resume}")
        _show_session_summary(session)

        # Check for pending experiments
        pending = store.get_pending_experiments()
        if not pending:
            console.print("  [af.muted]No pending experiments — nothing to resume.[/af.muted]")
            store.close()
            return

        console.print(
            f"  [af.primary]{len(pending)} pending "
            f"{term('experiments', len(pending)).lower()} to run[/af.primary]"
        )
        console.print()

        # Restart stopped instances
        from autofoundry.provisioner import (
            register_cleanup_handler,
            restart_instances,
            stop_instances,
            teardown_instances,
        )

        stored_instances = store.get_instances()
        instances = restart_instances(config, stored_instances, store)

        if not instances:
            print_error("No instances came back online. Aborting.")
            store.close()
            raise typer.Exit(1)

        register_cleanup_handler(config, instances)
        store.update_session_status(SessionStatus.RUNNING)

        # Run pending experiments
        from autofoundry.executor import run_all_experiments
        from autofoundry.reporter import print_report

        script_path = session.script_path
        num_pending = len(pending)

        print_header(TERMS['experiment'])
        console.print()
        console.print(
            f"  [af.primary]Resuming {num_pending} "
            f"{term('experiments', num_pending).lower()} across "
            f"{len(instances)} {term('instances', len(instances)).lower()}...[/af.primary]"
        )
        console.print()

        runs = run_all_experiments(
            instances,
            num_pending,
            script_path,
            config.ssh_key_path,
        )

        # Store results
        for run in runs:
            store.log_event("experiment_completed", {
                "experiment_index": run.experiment_index,
                "exit_code": run.exit_code or 0,
                "metrics": run.metrics,
            })

        # Report (include previously completed experiments too)
        print_report(runs)
        store.update_session_status(SessionStatus.REPORTING)

        # Teardown prompt
        console.print()
        action = Prompt.ask(
            f"  [af.label]What to do with {term('instances', len(instances)).lower()}?[/af.label]\n"
            "  [af.muted]  stop = release GPU, keep disk (fast restart later)\n"
            "  terminate = delete everything\n"
            "  keep = leave running[/af.muted]\n"
            "  [af.label]Choice[/af.label]",
            choices=["stop", "terminate", "keep"],
            default="stop",
        )

        if action == "stop":
            stop_instances(config, instances)
            store.update_session_status(SessionStatus.PAUSED)
            print_status("Status", "STANDBY — units stopped, disk preserved")
            print_status("Resume", f"autofoundry run --resume {resume}")
        elif action == "terminate":
            teardown_instances(config, instances)
            store.update_session_status(SessionStatus.COMPLETED)
        else:
            store.update_session_status(SessionStatus.PAUSED)
            print_status("Status", "STANDBY — units still running")
            print_status("Resume", f"autofoundry run --resume {resume}")

        store.close()
        return

    # New session
    if auto:
        # Non-interactive: require script argument, use defaults for rest
        if not script:
            print_error("--auto requires a script argument")
            raise typer.Exit(1)
        script_path = _resolve_script(script, config)
        num_experiments = num if num is not None else 1
        gpu_query = resolve_query(
            gpu_type=gpu, segment=segment,
            vram_min=min_vram, vram_max=max_vram,
            default_segment=config.default_segment,
            default_min_vram=config.default_min_vram or DEFAULT_MIN_VRAM,
        )
        if multi_gpu:
            gpu_query.single_gpu = False
        gpu_type = gpu_query.description
    else:
        script_path, num_experiments, gpu_query = _prompt_session_params(config, script)
        # Override with CLI flags if provided
        if num is not None:
            num_experiments = num
        if gpu:
            gpu_query = resolve_query(gpu_type=gpu)
        elif segment is not None or min_vram is not None or max_vram is not None:
            gpu_query = resolve_query(segment=segment, vram_min=min_vram, vram_max=max_vram)
        gpu_type = gpu_query.description
        if multi_gpu:
            gpu_query.single_gpu = False

    # Remember script for next time
    config.last_script = script_path

    session_id = config.next_operation_id
    config.save()

    session = Session(
        session_id=session_id,
        status=SessionStatus.PLANNING,
        script_path=script_path,
        total_experiments=num_experiments,
        gpu_type=gpu_type,
    )

    store = SessionStore(session_id)
    store.create_session(session)
    store.create_experiments(num_experiments)
    store.log_event("session_created", {"script_path": script_path, "gpu_type": gpu_type})

    _show_session_summary(session)

    # Resolve network volume (only when explicitly requested via --volume)
    volume_id = ""
    volume_region = ""
    vol_provider_filter = provider  # CLI --provider flag
    vol_region_filter = region      # CLI --region flag
    if volume:
        console.print()
        volume_id, volume_region, vol_pname = _resolve_volume(config, volume)
        if volume_id:
            vol_provider_filter = vol_pname
            console.print()

    # Planning — select providers/offers (filtered by volume constraints if any)
    if auto:
        from autofoundry.planner import auto_plan
        plan = auto_plan(
            config, gpu_query, num_experiments, script_path,
            provider_filter=vol_provider_filter, region_filter=vol_region_filter,
            datacenter_id=volume_region or None,
        )
    else:
        from autofoundry.planner import interactive_plan
        plan = interactive_plan(
            config, gpu_query, num_experiments, script_path,
            provider_filter=vol_provider_filter, region_filter=vol_region_filter,
            datacenter_id=volume_region or None,
        )
    if plan is None:
        store.update_session_status(SessionStatus.FAILED)
        store.close()
        raise typer.Exit(1)

    store.update_session_status(SessionStatus.PROVISIONING)

    # Provisioning
    from autofoundry.provisioner import (
        provision_instances,
        register_cleanup_handler,
        stop_instances,
        teardown_instances,
    )

    try:
        instances = provision_instances(
            config, plan, session_id, store,
            gpu_type_filter=gpu_type,
            volume_id=volume_id,
            volume_region=volume_region,
            script_path=script_path,
            image_override=image,
        )
    except KeyboardInterrupt:
        console.print()
        stored = store.get_instances()
        if stored:
            console.print(
                "  [af.alert]INTERRUPT — "
                f"{len(stored)} instance(s) already created[/af.alert]"
            )
            choice = Prompt.ask(
                f"\n  [af.muted]What to do with {term('instances', len(stored)).lower()}?\n"
                "  stop = release GPU, keep disk (fast restart later)\n"
                "  terminate = delete everything\n"
                "  keep = leave running[/af.muted]\n"
                "  [af.label]Choice[/af.label]",
                choices=["stop", "terminate", "keep"],
                default="stop",
            )
            if choice == "stop":
                stop_instances(config, stored)
                store.update_session_status(SessionStatus.PAUSED)
            elif choice == "terminate":
                teardown_instances(config, stored)
                store.update_session_status(SessionStatus.FAILED)
            else:
                console.print(
                    f"  [af.muted]Instances kept. Use 'autofoundry teardown' to clean up.[/af.muted]"
                )
                store.update_session_status(SessionStatus.PAUSED)
        else:
            store.update_session_status(SessionStatus.FAILED)
        store.close()
        raise typer.Exit(1)

    if not instances:
        print_error("No instances came online. Aborting.")
        store.update_session_status(SessionStatus.FAILED)
        store.close()
        raise typer.Exit(1)

    register_cleanup_handler(config, instances)
    store.update_session_status(SessionStatus.RUNNING)

    # Execution — forward env vars so scripts/executor can use them
    if image:
        os.environ["AUTOFOUNDRY_IMAGE"] = image
    if config.huggingface_token:
        os.environ["HUGGINGFACE_TOKEN"] = config.huggingface_token

    from autofoundry.executor import run_all_experiments
    from autofoundry.reporter import print_report

    print_header(TERMS['experiment'])
    console.print()
    console.print(
        f"  [af.primary]Deploying {num_experiments} "
        f"{term('experiments', num_experiments).lower()} across "
        f"{len(instances)} {term('instances', len(instances)).lower()}...[/af.primary]"
    )
    console.print()

    runs = run_all_experiments(
        instances,
        num_experiments,
        script_path,
        config.ssh_key_path,
    )

    # Store results
    for run in runs:
        store.log_event("experiment_completed", {
            "experiment_index": run.experiment_index,
            "exit_code": run.exit_code or 0,
            "metrics": run.metrics,
        })

    # Report
    print_report(runs)
    store.update_session_status(SessionStatus.REPORTING)

    # Teardown
    from autofoundry.provisioner import stop_instances

    console.print()
    if auto:
        action = "terminate"
        console.print("  [af.muted]Auto mode: terminating instances...[/af.muted]")
    else:
        action = Prompt.ask(
            f"  [af.label]What to do with {term('instances', len(instances)).lower()}?[/af.label]\n"
            "  [af.muted]  stop = release GPU, keep disk (fast restart later)\n"
            "  terminate = delete everything\n"
            "  keep = leave running[/af.muted]\n"
            "  [af.label]Choice[/af.label]",
            choices=["stop", "terminate", "keep"],
            default="stop",
        )

    if action == "stop":
        stop_instances(config, instances)
        store.update_session_status(SessionStatus.PAUSED)
        print_status("Status", "STANDBY — units stopped, disk preserved")
        print_status("Resume", f"autofoundry run --resume {session_id}")
    elif action == "terminate":
        teardown_instances(config, instances)
        store.update_session_status(SessionStatus.COMPLETED)
    else:
        store.update_session_status(SessionStatus.PAUSED)
        print_status("Status", "STANDBY — units still running")
        print_status("Resume", f"autofoundry run --resume {session_id}")

    store.close()


volumes_app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    invoke_without_command=True,
)
app.add_typer(volumes_app, name="volumes")


def _get_volume_providers(config: Config) -> list:
    """Return configured providers that support volumes."""
    from autofoundry.models import ProviderName

    VOLUME_PROVIDERS = {ProviderName.RUNPOD, ProviderName.LAMBDALABS}
    return [p for p in config.configured_providers if p in VOLUME_PROVIDERS]


@volumes_app.callback(context_settings={"help_option_names": []})
def _volumes_default(
    ctx: typer.Context,
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
) -> None:
    """Manage network volumes across providers."""
    if help_ or ctx.invoked_subcommand is None:
        print_banner(version=__version__)
        console.print()
        console.print("  [af.primary]autofoundry volumes[/af.primary] — [af.muted]Manage network volumes[/af.muted]")
        console.print()
        console.print("  [af.muted]COMMANDS:[/af.muted]")
        console.print("    [af.secondary]list[/af.secondary]     List network volumes across providers")
        console.print("    [af.secondary]create[/af.secondary]   Create a new network volume")
        console.print()
        if help_:
            raise typer.Exit()


@volumes_app.command("list", context_settings={"help_option_names": []})
def volumes_list(
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
) -> None:
    """List network volumes across all configured providers."""
    if help_:
        _print_command_help("autofoundry volumes list", "List network volumes across providers", [
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()
    from autofoundry.providers import get_provider
    from autofoundry.theme import make_table

    print_banner(version=__version__)
    console.print()
    config = _load_or_setup_config()

    eligible = _get_volume_providers(config)

    if not eligible:
        console.print("  [af.muted]No providers with volume support configured.[/af.muted]")
        console.print("  [af.muted]Supported: RunPod, Lambda Labs[/af.muted]")
        return

    all_volumes = []
    for provider_name in eligible:
        provider = get_provider(provider_name, config.api_keys[provider_name])
        if hasattr(provider, "list_volumes"):
            try:
                vols = provider.list_volumes()
                all_volumes.extend(vols)
            except Exception as e:
                print_error(f"Failed to list volumes for {provider_name.value}: {e}")

    if not all_volumes:
        console.print("  [af.muted]No volumes found.[/af.muted]")
        console.print()
        return

    table = make_table("NETWORK VOLUMES", [
        ("Provider", "af.secondary"),
        ("Name", "af.primary"),
        ("Size", ""),
        ("Region", ""),
        ("Mount Path", "af.muted"),
        ("ID", "af.muted"),
    ])

    for vol in all_volumes:
        from autofoundry.config import PROVIDER_DISPLAY

        table.add_row(
            PROVIDER_DISPLAY.get(vol.provider, vol.provider.value),
            vol.name,
            f"{vol.size_gb}GB",
            vol.region,
            vol.mount_path,
            vol.volume_id[:12],
        )

    console.print(table)
    console.print()


@volumes_app.command("create", context_settings={"help_option_names": []})
def volumes_create(
    name: str = typer.Option(None, "--name", "-n", help="Volume name"),
    provider_opt: str = typer.Option(None, "--provider", "-p", help="Provider (runpod, lambdalabs)"),
    size: int = typer.Option(None, "--size", "-s", help="Size in GB (RunPod only)"),
    region: str = typer.Option(None, "--region", "-r", help="Region / data center ID"),
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
) -> None:
    """Create a new network volume."""
    if help_:
        _print_command_help("autofoundry volumes create", "Create a new network volume", [
            ("--name, -n TEXT", "Volume name"),
            ("--provider, -p TEXT", "Provider (runpod, lambdalabs)"),
            ("--size, -s INT", "Size in GB (RunPod only, default: 100)"),
            ("--region, -r TEXT", "Region / data center ID"),
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()
    from rich.prompt import Confirm as RichConfirm

    from autofoundry.models import ProviderName
    from autofoundry.providers import get_provider

    print_banner(version=__version__)
    config = _load_or_setup_config()

    eligible = _get_volume_providers(config)

    if not eligible:
        console.print("  [af.muted]No providers with volume support configured.[/af.muted]")
        console.print("  [af.muted]Supported: RunPod, Lambda Labs[/af.muted]")
        return

    # Resolve provider
    if provider_opt:
        try:
            provider_name = ProviderName(provider_opt)
        except ValueError:
            print_error(f"Unknown provider: {provider_opt}")
            print_error(f"Available: {', '.join(p.value for p in eligible)}")
            return
        if provider_name not in eligible:
            print_error(f"{provider_opt} is not configured or doesn't support volumes.")
            return
    elif len(eligible) == 1:
        provider_name = eligible[0]
    else:
        choice = Prompt.ask(
            "  [af.label]Provider[/af.label]",
            choices=[p.value for p in eligible],
        )
        provider_name = ProviderName(choice)

    from autofoundry.config import PROVIDER_DISPLAY

    print_status("Provider", PROVIDER_DISPLAY.get(provider_name, provider_name.value))

    # Resolve name
    if not name:
        name = Prompt.ask("  [af.label]Volume name[/af.label]")

    # Resolve size & region per provider
    if provider_name == ProviderName.RUNPOD:
        if size is None:
            size = IntPrompt.ask("  [af.label]Volume size (GB)[/af.label]", default=100)
        if not region:
            region = Prompt.ask("  [af.label]Data center ID[/af.label]", default="US-TX-3")

        if not RichConfirm.ask(
            f"  [af.label]Create {size}GB volume '{name}' in {region}?[/af.label]",
            default=True,
        ):
            return

        provider = get_provider(provider_name, config.api_keys[provider_name])
        vol = provider.create_volume(name, size, region)

    elif provider_name == ProviderName.LAMBDALABS:
        if not region:
            region = Prompt.ask("  [af.label]Region[/af.label]", default="us-east-1")

        if not RichConfirm.ask(
            f"  [af.label]Create volume '{name}' in {region}?[/af.label]",
            default=True,
        ):
            return

        provider = get_provider(provider_name, config.api_keys[provider_name])
        vol = provider.create_volume(name, region)

    else:
        print_error(f"Volume creation not supported for {provider_name.value}")
        return

    console.print()
    print_success(f"Volume created: {vol.name}")
    print_status("ID", vol.volume_id)
    print_status("Region", vol.region)
    if vol.size_gb:
        print_status("Size", f"{vol.size_gb}GB")
    print_status("Mount path", vol.mount_path)
    console.print()
    console.print(f"  [af.muted]Use with:[/af.muted] [af.primary]autofoundry run <script> --volume {vol.name}[/af.primary]")
    console.print()


@app.command(context_settings={"help_option_names": []})
def inventory(
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
    gpu: str = typer.Option(None, "--gpu", "-g", help="GPU type to filter (e.g. H100)"),
    segment: str = typer.Option(None, "--segment", "-s", help="GPU segment (consumer, workstation, datacenter)"),
    min_vram: float = typer.Option(None, "--min-vram", help="Minimum VRAM in GB (e.g. 80)"),
    max_vram: float = typer.Option(None, "--max-vram", help="Maximum VRAM in GB"),
    multi_gpu: bool = typer.Option(False, "--multi-gpu", help="Include multi-GPU instances"),
) -> None:
    """Browse GPU inventory across all configured supply lines."""
    if help_:
        _print_command_help("autofoundry inventory", "Browse GPU inventory across supply lines", [
            ("--gpu, -g TEXT", "GPU type to filter (e.g. H100)"),
            ("--segment, -s TEXT", "GPU segment (consumer, workstation, datacenter)"),
            ("--min-vram FLOAT", "Minimum VRAM in GB (e.g. 80)"),
            ("--max-vram FLOAT", "Maximum VRAM in GB"),
            ("--multi-gpu", "Include multi-GPU instances"),
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()
    from autofoundry.planner import display_offers, query_all_offers

    print_banner(version=__version__)
    config = _load_or_setup_config()

    if gpu:
        query = resolve_query(gpu_type=gpu)
    elif segment is not None or min_vram is not None or max_vram is not None:
        query = resolve_query(segment=segment, vram_min=min_vram, vram_max=max_vram)
    else:
        query = _prompt_tier_selection(config.default_segment, config.default_min_vram)

    if multi_gpu:
        query.single_gpu = False

    print_status("Searching for", query.description)
    console.print()

    all_offers = query_all_offers(config, query)
    if not all_offers:
        print_error(f"No inventory found for {query.description}")
        raise typer.Exit(1)

    display_offers(all_offers, truncate=False)


@app.command(context_settings={"help_option_names": []})
def status(
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
    session_id: str = typer.Argument(None, help="Operation ID (default: most recent)"),
) -> None:
    """Show status of operations and their instances."""
    if help_:
        _print_command_help("autofoundry status", "Show status of operations and instances", [
            ("[SESSION_ID]", "Operation ID (default: all operations)"),
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()
    print_banner(version=__version__)

    sessions = SessionStore.list_sessions()
    if not sessions:
        console.print("  [af.muted]No operations found.[/af.muted]")
        return

    if session_id is None:
        # Show all sessions
        print_header(f"{TERMS['session']} STATUS")
        console.print()
        for sid in sessions:
            store = SessionStore(sid)
            session = store.get_session()
            if session:
                status_style = "af.success" if session.status == SessionStatus.COMPLETED else "af.primary"
                print_status(sid, f"{display_status(session.status.value)} — {session.gpu_type} — {session.total_experiments} {term('experiments', session.total_experiments).lower()}", style=status_style)
            store.close()
        console.print()
        return

    if session_id not in sessions:
        print_error(f"Operation '{session_id}' not found")
        print_status("Available", ", ".join(sessions) if sessions else "(none)")
        raise typer.Exit(1)

    store = SessionStore(session_id)
    session = store.get_session()
    if session is None:
        print_error(f"Could not load operation '{session_id}'")
        store.close()
        raise typer.Exit(1)

    _show_session_summary(session)
    print_status("Status", display_status(session.status.value))

    instances = store.get_instances()
    if instances:
        console.print()
        print_header(f"{TERMS['instances']}")
        console.print()
        for inst in instances:
            ssh_info = f" — {inst.ssh.host}:{inst.ssh.port}" if inst.ssh else ""
            print_status(inst.instance_id, f"{inst.provider.value} {inst.gpu_type} [{display_status(inst.status.value)}]{ssh_info}")

    completed = store.get_completed_experiments()
    pending = store.get_pending_experiments()
    console.print()
    print_status("Completed", str(len(completed)))
    print_status("Pending", str(len(pending)))

    store.close()


@app.command(context_settings={"help_option_names": []})
def results(
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
    session_id: str = typer.Argument(None, help="Operation ID (default: most recent)"),
) -> None:
    """View experiment results and metrics from a completed operation."""
    if help_:
        _print_command_help("autofoundry results", "View experiment results and metrics", [
            ("[SESSION_ID]", "Operation ID (default: most recent)"),
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()
    from autofoundry.executor import ExperimentRun
    from autofoundry.models import InstanceInfo, InstanceStatus, ProviderName

    print_banner(version=__version__)

    sessions = SessionStore.list_sessions()
    if not sessions:
        console.print("  [af.muted]No operations found.[/af.muted]")
        return

    # Default to most recent session
    if session_id is None:
        session_id = sessions[-1]

    if session_id not in sessions:
        print_error(f"Operation '{session_id}' not found")
        print_status("Available", ", ".join(sessions) if sessions else "(none)")
        raise typer.Exit(1)

    store = SessionStore(session_id)
    session = store.get_session()
    if session is None:
        print_error(f"Could not load operation '{session_id}'")
        store.close()
        raise typer.Exit(1)

    _show_session_summary(session)

    completed = store.get_completed_experiments()
    if not completed:
        console.print("  [af.muted]No completed experiments yet.[/af.muted]")
        store.close()
        return

    # Build instance lookup from stored instances
    instances_by_id = {inst.instance_id: inst for inst in store.get_instances()}

    # Convert ExperimentResult → ExperimentRun for the reporter
    from autofoundry.reporter import print_report

    placeholder = InstanceInfo(
        provider=ProviderName.RUNPOD, instance_id="unknown", name="unknown",
        status=InstanceStatus.DELETED, gpu_type=session.gpu_type,
    )
    runs = []
    for exp in completed:
        instance = instances_by_id.get(exp.instance_id, placeholder)
        runs.append(ExperimentRun(
            instance=instance,
            experiment_index=exp.run_index,
            exit_code=exp.exit_code,
            metrics=exp.metrics,
            output_lines=exp.raw_output.splitlines() if exp.raw_output else [],
        ))

    print_report(runs)
    store.close()


@app.command(context_settings={"help_option_names": []})
def teardown(
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
    session_id: str = typer.Argument(None, help="Operation ID to tear down"),
) -> None:
    """Terminate all instances for an operation."""
    if help_:
        _print_command_help("autofoundry teardown", "Terminate all instances for an operation", [
            ("SESSION_ID", "Operation ID to tear down (required)"),
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()
    if session_id is None:
        print_error("SESSION_ID is required")
        raise typer.Exit(1)
    from autofoundry.provisioner import teardown_instances as do_teardown

    print_banner(version=__version__)
    config = _load_or_setup_config()

    sessions = SessionStore.list_sessions()
    if session_id not in sessions:
        print_error(f"Operation '{session_id}' not found")
        print_status("Available", ", ".join(sessions) if sessions else "(none)")
        raise typer.Exit(1)

    store = SessionStore(session_id)
    instances = store.get_instances()

    if not instances:
        console.print("  [af.muted]No instances found for this operation.[/af.muted]")
        store.close()
        return

    console.print(f"  [af.primary]{len(instances)} {term('instances', len(instances)).lower()} to terminate:[/af.primary]")
    for inst in instances:
        print_status(inst.instance_id, f"{inst.provider.value} {inst.gpu_type} [{display_status(inst.status.value)}]")
    console.print()

    from rich.prompt import Confirm as RichConfirm

    if not RichConfirm.ask("  [af.alert]Confirm termination?[/af.alert]", default=False):
        console.print("  [af.muted]Aborted.[/af.muted]")
        store.close()
        return

    do_teardown(config, instances)
    store.update_session_status(SessionStatus.COMPLETED)
    store.close()
    print_success(f"Operation {session_id} terminated")


def main() -> None:
    try:
        app(standalone_mode=False)
    except click.exceptions.UsageError as e:
        print_banner(version=__version__)
        console.print()
        print_error(str(e))
        console.print()
        raise SystemExit(e.exit_code) from None
