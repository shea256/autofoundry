"""Serverless CLI: local plans, bounded jobs and scoped cleanup."""

from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path
from uuid import uuid4

import typer
from pydantic import ValidationError

from autofoundry.config import CONFIG_DIR
from autofoundry.gpu_filter import VALID_SEGMENTS, resolve_query
from autofoundry.providers.modal import (
    DEFAULT_IMAGE,
    ModalError,
    ModalJobSpec,
    ModalProvider,
    select_offer,
)
from autofoundry.theme import console, print_error

app = typer.Typer(help="Modal serverless jobs; no persistent hosts or SSH.", no_args_is_help=True)


def execute_modal(
    script: str,
    *,
    gpu: str | None = None,
    segment: str | None = None,
    min_vram: float | None = None,
    max_vram: float | None = None,
    gpu_count: int = 1,
    region: str | None = None,
    image: str | None = None,
    volume: str | None = None,
    app_name: str = "autofoundry",
    cpu: float = 2,
    memory_mib: int = 16384,
    timeout: int = 3600,
    artifacts: list[str] | None = None,
    num: int = 1,
    dry_run: bool = False,
    output: Path | None = None,
) -> None:
    from autofoundry.provisioner import parse_script_images

    try:
        if segment and segment.lower() not in VALID_SEGMENTS:
            raise ModalError("Unknown GPU segment")
        if num < 1:
            raise ModalError("--num must be positive")
        if not Path(script).expanduser().is_file():
            raise ModalError("Experiment script must be a local file")
        query = resolve_query(gpu_type=gpu, segment=segment, vram_min=min_vram, vram_max=max_vram)
        # Explicit GPU must not discard per-GPU memory requirements.
        if min_vram is not None:
            query.vram_min = min_vram
        if max_vram is not None:
            query.vram_max = max_vram
        offer = select_offer(query, gpu_count)
        spec = ModalJobSpec(
            script=script,
            app_name=app_name,
            gpu=offer.gpu_type,
            gpu_count=gpu_count,
            region=region.lower() if region else None,
            image=image or parse_script_images(script).get("modal") or DEFAULT_IMAGE,
            volume=volume,
            cpu=cpu,
            memory_mib=memory_mib,
            timeout_seconds=timeout,
            artifacts=artifacts or [],
        )
    except (ModalError, ValidationError) as exc:
        # ValidationError contains raw inputs; show messages only.
        message = (
            "; ".join(e["msg"] for e in exc.errors())
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        print_error(message)
        raise typer.Exit(1) from None
    console.print(
        json.dumps(
            {"request": spec.model_dump(), "estimate_per_job": spec.estimate(), "jobs": num},
            indent=2,
        ),
        markup=False,
    )
    if dry_run:
        return  # No SDK imports, token reads or network operations.
    root = output or CONFIG_DIR / "modal-jobs"
    provider = ModalProvider()
    failed = False

    async def run_jobs():
        nonlocal failed
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        previous = signal.getsignal(signal.SIGTERM)
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
        try:
            for _ in range(num):
                directory = root / f"af-{uuid4().hex}"
                console.print(f"Modal job record: {directory / 'job.json'}", markup=False)
                result = await provider.run_job(spec, directory)
                console.print(
                    json.dumps(
                        {
                            k: result.get(k)
                            for k in ("status", "exit_code", "metrics", "cleanup", "error")
                        }
                    ),
                    markup=False,
                )
                failed |= result["status"] != "completed" or result["cleanup"] != "terminated"
                if result["cleanup"] == "unconfirmed":
                    console.print(
                        f"Retry cleanup: autofoundry modal cleanup {directory}", markup=False
                    )
                    break  # Do not accumulate resources after an ambiguous create/cleanup.
        finally:
            loop.remove_signal_handler(signal.SIGTERM)
            signal.signal(signal.SIGTERM, previous)

    try:
        asyncio.run(run_jobs())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print_error("Modal job interrupted; inspect the printed job record for cleanup status")
        raise typer.Exit(130) from None
    except ModalError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from None
    if failed:
        raise typer.Exit(1)


@app.command("run")
def run(
    script: str = typer.Argument(...),
    gpu: str | None = typer.Option(None),
    segment: str | None = typer.Option(None),
    min_vram: float | None = typer.Option(None),
    max_vram: float | None = typer.Option(None),
    gpu_count: int = typer.Option(1),
    region: str | None = typer.Option(None),
    image: str | None = typer.Option(None),
    volume: str | None = typer.Option(None, help="Existing Volume mounted at /workspace"),
    app_name: str = typer.Option("autofoundry", "--app", help="Existing Modal App"),
    cpu: float = typer.Option(2, help="Physical cores (request and hard limit)"),
    memory_mib: int = typer.Option(16384, help="RAM MiB (request and hard limit)"),
    timeout: int = typer.Option(3600, help="Maximum Sandbox lifetime, seconds (1–86400)"),
    artifact: list[str] | None = typer.Option(None, help="Explicit /workspace file to download"),
    num: int = typer.Option(1, help="Sequential independent jobs; no automatic retries"),
    dry_run: bool = typer.Option(False, help="Local plan only; no credentials or remote calls"),
    output: Path | None = typer.Option(None, help="Parent directory for local job records/results"),
):
    execute_modal(
        script,
        gpu=gpu,
        segment=segment,
        min_vram=min_vram,
        max_vram=max_vram,
        gpu_count=gpu_count,
        region=region,
        image=image,
        volume=volume,
        app_name=app_name,
        cpu=cpu,
        memory_mib=memory_mib,
        timeout=timeout,
        artifacts=artifact,
        num=num,
        dry_run=dry_run,
        output=output,
    )


@app.command("cleanup")
def cleanup(directory: Path = typer.Argument(..., exists=True, file_okay=False)):
    """Terminate only the Sandbox in this local job record; never delete storage."""
    try:
        asyncio.run(ModalProvider().cleanup_job(directory))
    except (ModalError, OSError, ValueError, KeyError):
        print_error("Cleanup unconfirmed. Check this job's record and Modal workspace/profile.")
        raise typer.Exit(1) from None
    console.print("Cleanup complete; Apps and Volumes retained.")


@app.command("auth-check")
def auth_check():
    """Check official SDK authentication without allocating compute or creating resources."""
    try:
        asyncio.run(ModalProvider().validate_auth())
    except ModalError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from None
    console.print("Modal authentication succeeded.")
