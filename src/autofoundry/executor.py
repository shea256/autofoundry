"""Remote execution engine — upload scripts and stream output via SSH."""

from __future__ import annotations

import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07|\r")

from autofoundry.models import InstanceInfo, SshConnectionInfo
from autofoundry.theme import TERMS, console, print_error, print_success


@dataclass
class ExperimentRun:
    """Tracks a single experiment execution on an instance."""

    instance: InstanceInfo
    experiment_index: int
    output_lines: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    exit_code: int | None = None
    error: str = ""


def _ssh_opts(ssh_key_path: str) -> list[str]:
    """Common SSH options for non-interactive use."""
    return [
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-o", "ConnectTimeout=30",
        "-o", "BatchMode=yes",
        "-o", "PasswordAuthentication=no",
        "-i", ssh_key_path,
    ]


def upload_script(
    ssh: SshConnectionInfo,
    local_path: str,
    ssh_key_path: str,
    remote_path: str = "/workspace/run_experiment.sh",
) -> bool:
    """Upload a script to the remote instance via scp."""
    scp_cmd = [
        "scp",
        *_ssh_opts(ssh_key_path),
        "-P", str(ssh.port),
        local_path,
        f"{ssh.username}@{ssh.host}:{remote_path}",
    ]
    try:
        result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print_error("SCP: upload timed out after 60s")
        return False
    if result.returncode != 0 and result.stderr:
        print_error(f"SCP: {result.stderr.strip()}")
    return result.returncode == 0


def run_remote(
    ssh: SshConnectionInfo,
    ssh_key_path: str,
    command: str,
    unit_label: str,
    on_line: callable | None = None,
) -> tuple[int, list[str]]:
    """Execute a command on the remote instance, streaming output line by line."""
    ssh_cmd = [
        "ssh",
        *_ssh_opts(ssh_key_path),
        "-p", str(ssh.port),
        f"{ssh.username}@{ssh.host}",
        # PYTHONUNBUFFERED forces line-buffered output without a PTY,
        # avoiding ANSI escape code noise from progress bars
        f"PYTHONUNBUFFERED=1 {command}",
    ]

    lines: list[str] = []
    proc = subprocess.Popen(
        ssh_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    for line in proc.stdout:
        line = _ANSI_RE.sub("", line).rstrip("\n")
        if not line:
            continue
        lines.append(line)
        if on_line:
            on_line(unit_label, line)

    proc.wait()
    return proc.returncode, lines


def parse_metrics(lines: list[str]) -> dict[str, float]:
    """Parse key-value metrics from output after a --- delimiter."""
    metrics: dict[str, float] = {}
    in_results = False
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            in_results = True
            continue
        if in_results and ":" in stripped:
            key, _, value = stripped.partition(":")
            try:
                metrics[key.strip()] = float(value.strip().rstrip("%"))
            except ValueError:
                pass
    return metrics


def execute_experiment(
    instance: InstanceInfo,
    experiment_index: int,
    script_path: str,
    ssh_key_path: str,
    unit_num: int,
) -> ExperimentRun:
    """Upload and execute a script on one instance, streaming output."""
    run = ExperimentRun(instance=instance, experiment_index=experiment_index)
    ssh = instance.ssh
    if ssh is None:
        run.error = "No SSH connection info"
        run.exit_code = -1
        return run

    unit_label = f"UNIT-{unit_num:02d}"

    # Verify SSH connectivity (key auth can lag behind port availability)
    for attempt in range(10):
        try:
            test = subprocess.run(
                ["ssh", *_ssh_opts(ssh_key_path),
                 "-p", str(ssh.port),
                 f"{ssh.username}@{ssh.host}", "echo ok"],
                capture_output=True, text=True, timeout=20,
            )
        except subprocess.TimeoutExpired:
            test = None
        if test and test.returncode == 0:
            break
        detail = ""
        if test and test.stderr:
            detail = f" ({test.stderr.strip()})"
        elif test is None:
            detail = " (timeout)"
        if attempt < 9:
            console.print(
                f"  [af.muted]{unit_label} SSH not ready{detail}, "
                f"retrying ({attempt + 1}/10)...[/af.muted]"
            )
            time.sleep(5)
    else:
        run.error = "SSH key auth failed"
        run.exit_code = -1
        print_error(f"{unit_label} SSH auth failed — check key config")
        return run

    # Upload script
    console.print(f"  [af.muted]{unit_label} uploading script...[/af.muted]")
    if not upload_script(ssh, script_path, ssh_key_path):
        run.error = "Script upload failed"
        run.exit_code = -1
        print_error(f"{unit_label} script upload failed")
        return run

    # Execute
    console.print(
        f"  [af.secondary]{unit_label} executing "
        f"{TERMS['experiment'].lower()} #{experiment_index + 1}...[/af.secondary]"
    )

    def on_line(label: str, line: str) -> None:
        console.print(f"  [af.muted]{label}[/af.muted] {line}")

    exit_code, lines = run_remote(
        ssh,
        ssh_key_path,
        "chmod +x /workspace/run_experiment.sh && stdbuf -oL /workspace/run_experiment.sh",
        unit_label,
        on_line=on_line,
    )

    run.output_lines = lines
    run.exit_code = exit_code
    run.metrics = parse_metrics(lines)

    exp_label = f"{TERMS['experiment'].lower()} #{experiment_index + 1}"
    if exit_code == 0:
        print_success(f"{unit_label} {exp_label} completed")
    else:
        run.error = f"Exit code {exit_code}"
        print_error(f"{unit_label} {exp_label} failed (exit {exit_code})")

    return run


def run_all_experiments(
    instances: list[InstanceInfo],
    total_experiments: int,
    script_path: str,
    ssh_key_path: str,
) -> list[ExperimentRun]:
    """Distribute experiments across instances and run them.

    Round-robin assignment: experiment i goes to instance i % N.
    Sequential on each instance to avoid GPU contention.
    Parallel across instances via threads.
    """
    if not instances:
        return []

    # Assign experiments to instances (round-robin)
    assignments: dict[int, list[int]] = {i: [] for i in range(len(instances))}
    for exp_idx in range(total_experiments):
        instance_idx = exp_idx % len(instances)
        assignments[instance_idx].append(exp_idx)

    all_runs: list[ExperimentRun] = []
    lock = threading.Lock()

    def run_on_instance(instance_idx: int) -> None:
        instance = instances[instance_idx]
        unit_num = instance_idx + 1
        for exp_idx in assignments[instance_idx]:
            result = execute_experiment(
                instance, exp_idx, script_path, ssh_key_path, unit_num
            )
            with lock:
                all_runs.append(result)

    threads = []
    for idx in range(len(instances)):
        if not assignments[idx]:
            continue
        t = threading.Thread(target=run_on_instance, args=(idx,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return all_runs
