"""Main CLI entry point for autofoundry."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.prompt import IntPrompt, Prompt

from autofoundry import __version__
from autofoundry.config import Config, first_run_setup
from autofoundry.models import Session, SessionStatus
from autofoundry.state import SessionStore
from autofoundry.theme import (
    TERMS,
    console,
    print_banner,
    print_error,
    print_header,
    print_status,
    print_success,
)

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


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


@app.command()
def run(
    script: str = typer.Argument(None, help="Path to the script to run on GPU instances"),
    resume: str = typer.Option(None, "--resume", "-r", help="Resume a previous operation"),
    num: int = typer.Option(None, "--num", "-n", help="Number of experiment runs"),
    gpu: str = typer.Option(None, "--gpu", "-g", help="GPU type (e.g. H100)"),
) -> None:
    """Launch autofoundry — GPU experiment orchestration engine."""
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
        # TODO: resume from last state (Phase 6)
        console.print("  [af.muted]Resume logic not yet implemented[/af.muted]")
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

    # Planning
    from autofoundry.planner import interactive_plan

    plan = interactive_plan(config, gpu_type, num_experiments, script_path)
    if plan is None:
        store.update_session_status(SessionStatus.FAILED)
        store.close()
        raise typer.Exit(1)

    store.update_session_status(SessionStatus.PROVISIONING)

    # Provisioning
    from autofoundry.provisioner import (
        provision_instances,
        register_cleanup_handler,
        teardown_instances,
    )

    instances = provision_instances(config, plan, session_id, store)
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
    from rich.prompt import Confirm as RichConfirm

    if RichConfirm.ask(
        f"  [af.label]Terminate all {TERMS['instances'].lower()}?[/af.label]",
        default=True,
    ):
        teardown_instances(config, instances)
        store.update_session_status(SessionStatus.COMPLETED)
    else:
        store.update_session_status(SessionStatus.PAUSED)
        print_status("Status", "PAUSED — instances still running")
        print_status("Resume", f"autofoundry --resume {session_id}")

    store.close()


def main() -> None:
    app()
