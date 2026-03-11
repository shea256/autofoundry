"""Main CLI entry point for autofoundry."""

from __future__ import annotations

from pathlib import Path

import click
import typer
from rich.prompt import IntPrompt, Prompt

from autofoundry import __version__
from autofoundry.config import Config, first_run_setup
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
)


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
        console.print("    [af.secondary]reserves[/af.secondary]  Browse GPU reserves across supply lines")
        console.print("    [af.secondary]volumes[/af.secondary]   List network volumes across providers")
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

    # Try last-used script as default
    default = config.last_script if config.last_script else None

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
) -> tuple[str, int, str]:
    """Prompt user for script path, experiment count, and GPU type."""
    print_header(f"{TERMS['experiments']} CONFIGURATION")
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

    # GPU type
    gpu_type = Prompt.ask(
        "  [af.label]GPU type[/af.label]",
        default=config.default_gpu_type,
    )

    return script_path, num_experiments, gpu_type


def _show_session_summary(session: Session) -> None:
    """Display session configuration summary."""
    console.print()
    print_status(TERMS["session"], session.session_id)
    print_status("Script", session.script_path)
    print_status(TERMS["experiments"], str(session.total_experiments))
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


def _resolve_volume(
    config: Config, volume_name: str, plan_providers: set,
) -> str:
    """Resolve a volume name to a volume ID, creating if necessary.

    Returns the volume ID string, or empty string if volumes aren't supported.
    """
    from autofoundry.models import ProviderName
    from autofoundry.providers import get_provider

    VOLUME_PROVIDERS = {ProviderName.RUNPOD, ProviderName.LAMBDALABS}
    eligible = plan_providers & VOLUME_PROVIDERS

    if not eligible:
        unsupported = ", ".join(p.value for p in plan_providers)
        print_error(f"Network volumes not supported on: {unsupported}")
        return ""

    # Use the first eligible provider (typically only one provider per plan)
    provider_name = next(iter(eligible))
    provider = get_provider(provider_name, config.api_keys[provider_name])

    if not hasattr(provider, "list_volumes"):
        print_error(f"Volume support not implemented for {provider_name.value}")
        return ""

    # Check for existing volume with this name
    console.print(f"  [af.muted]Checking for volume '{volume_name}'...[/af.muted]")
    volumes = provider.list_volumes()
    for vol in volumes:
        if vol.name == volume_name:
            print_success(f"Found volume: {vol.name} ({vol.size_gb}GB, {vol.region})")
            print_status("Mount path", vol.mount_path)
            return vol.volume_id

    # Volume doesn't exist — create it
    console.print(f"  [af.muted]Volume '{volume_name}' not found. Creating...[/af.muted]")
    console.print()

    from rich.prompt import Confirm as RichConfirm

    size_gb = IntPrompt.ask(
        "  [af.label]Volume size (GB)[/af.label]",
        default=100,
    )

    if provider_name == ProviderName.RUNPOD:
        region = Prompt.ask(
            "  [af.label]Data center ID[/af.label]",
            default="US-TX-3",
        )
        if not RichConfirm.ask(
            f"  [af.label]Create {size_gb}GB volume in {region}?[/af.label]",
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
    volume: str = typer.Option(None, "--volume", "-v", help="Network volume name (creates if needed)"),
) -> None:
    """Launch autofoundry — GPU experiment orchestration engine."""
    if help_:
        _print_command_help("autofoundry run", "GPU experiment orchestration engine", [
            ("[SCRIPT]", "Path to the script to run on GPU instances"),
            ("--resume, -r TEXT", "Resume a previous operation"),
            ("--num, -n INTEGER", "Number of experiment runs"),
            ("--gpu, -g TEXT", "GPU type (e.g. H100)"),
            ("--volume, -v TEXT", "Network volume name (creates if needed)"),
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
            f"{TERMS['experiments'].lower()} to run[/af.primary]"
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

        print_header(f"{TERMS['experiments']} EXECUTION")
        console.print()
        console.print(
            f"  [af.primary]Resuming {num_pending} "
            f"{TERMS['experiments'].lower()} across "
            f"{len(instances)} {TERMS['instances'].lower()}...[/af.primary]"
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
            f"  [af.label]What to do with {TERMS['instances'].lower()}?[/af.label]\n"
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
    script_path, num_experiments, gpu_type = _prompt_session_params(config, script)

    # Override with CLI flags if provided
    if num is not None:
        num_experiments = num
    if gpu is not None:
        gpu_type = gpu

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

    # Planning — select providers/offers
    from autofoundry.planner import interactive_plan

    plan = interactive_plan(config, gpu_type, num_experiments, script_path)
    if plan is None:
        store.update_session_status(SessionStatus.FAILED)
        store.close()
        raise typer.Exit(1)

    # Resolve network volume if requested
    volume_id = ""
    if volume:
        plan_providers = {offer.provider for offer, _ in plan.offers}
        console.print()
        volume_id = _resolve_volume(config, volume, plan_providers)
        if volume_id:
            console.print()

    store.update_session_status(SessionStatus.PROVISIONING)

    # Provisioning
    from autofoundry.provisioner import (
        provision_instances,
        register_cleanup_handler,
        teardown_instances,
    )

    instances = provision_instances(
        config, plan, session_id, store,
        gpu_type_filter=gpu_type,
        volume_id=volume_id,
    )
    if not instances:
        print_error("No instances came online. Aborting.")
        store.update_session_status(SessionStatus.FAILED)
        store.close()
        raise typer.Exit(1)

    register_cleanup_handler(config, instances)
    store.update_session_status(SessionStatus.RUNNING)

    # Execution
    from autofoundry.executor import run_all_experiments
    from autofoundry.reporter import print_report

    print_header(f"{TERMS['experiments']} EXECUTION")
    console.print()
    console.print(
        f"  [af.primary]Deploying {num_experiments} "
        f"{TERMS['experiments'].lower()} across "
        f"{len(instances)} {TERMS['instances'].lower()}...[/af.primary]"
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
    action = Prompt.ask(
        f"  [af.label]What to do with {TERMS['instances'].lower()}?[/af.label]\n"
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


@app.command(context_settings={"help_option_names": []})
def volumes(
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
) -> None:
    """List network volumes across all configured providers."""
    if help_:
        _print_command_help("autofoundry volumes", "List network volumes across providers", [
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()
    from autofoundry.models import ProviderName
    from autofoundry.providers import get_provider
    from autofoundry.theme import make_table

    print_banner(version=__version__)
    config = _load_or_setup_config()

    VOLUME_PROVIDERS = {ProviderName.RUNPOD, ProviderName.LAMBDALABS}
    eligible = [p for p in config.configured_providers if p in VOLUME_PROVIDERS]

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


@app.command(context_settings={"help_option_names": []})
def reserves(
    help_: bool = typer.Option(False, "--help", "-h", is_eager=True, help="Show help"),
    gpu: str = typer.Option(None, "--gpu", "-g", help="GPU type to filter (e.g. H100)"),
) -> None:
    """Browse GPU reserves across all configured supply lines."""
    if help_:
        _print_command_help("autofoundry reserves", "Browse GPU reserves across supply lines", [
            ("--gpu, -g TEXT", "GPU type to filter (e.g. H100)"),
            ("--help, -h", "Show this help"),
        ])
        raise typer.Exit()
    from autofoundry.planner import display_offers, query_all_offers

    print_banner(version=__version__)
    config = _load_or_setup_config()

    gpu_type = gpu or config.default_gpu_type
    print_status("Searching for", gpu_type)
    console.print()

    all_offers = query_all_offers(config, gpu_type)
    if not all_offers:
        print_error(f"No reserves found for {gpu_type}")
        raise typer.Exit(1)

    display_offers(all_offers)


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
                print_status(sid, f"{display_status(session.status.value)} — {session.gpu_type} — {session.total_experiments} {TERMS['experiments'].lower()}", style=status_style)
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

    console.print(f"  [af.primary]{len(instances)} {TERMS['instances'].lower()} to terminate:[/af.primary]")
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
