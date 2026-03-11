"""Results reporting for completed experiments."""

from __future__ import annotations

from autofoundry.executor import ExperimentRun
from autofoundry.theme import TERMS, console, make_table, print_header, print_status


def print_report(runs: list[ExperimentRun]) -> None:
    """Display a summary report of all experiment runs."""
    print_header(TERMS["results"])
    console.print()

    if not runs:
        console.print("  [af.muted]No experiment results to report.[/af.muted]")
        return

    # Results table
    succeeded = [r for r in runs if r.exit_code == 0]
    failed = [r for r in runs if r.exit_code != 0]

    print_status("Completed", f"{len(succeeded)}/{len(runs)}")
    if failed:
        print_status("Failed", str(len(failed)), style="af.alert")
    console.print()

    # Show metrics if any experiments produced them
    all_metrics: dict[str, list[float]] = {}
    for run in succeeded:
        for key, value in run.metrics.items():
            all_metrics.setdefault(key, []).append(value)

    if all_metrics:
        table = make_table(
            f"{TERMS['results']} — METRICS",
            [
                ("Metric", "af.secondary"),
                ("Best", "af.highlight"),
                ("Mean", "af.success"),
                ("Worst", "af.muted"),
                ("N", "af.muted"),
            ],
        )
        for metric, values in sorted(all_metrics.items()):
            table.add_row(
                metric,
                f"{min(values):.4f}",
                f"{sum(values) / len(values):.4f}",
                f"{max(values):.4f}",
                str(len(values)),
            )
        console.print(table)
        console.print()

    # Per-experiment details
    if len(runs) > 1:
        detail_table = make_table(
            f"{TERMS['experiments']} DETAIL",
            [
                ("#", "af.muted"),
                (TERMS["instance"], "af.secondary"),
                ("Status", ""),
                ("Metrics", "af.success"),
            ],
        )
        for run in sorted(runs, key=lambda r: r.experiment_index):
            unit_idx = runs.index(run)
            if run.exit_code == 0:
                status = "[af.success]OK[/af.success]"
            else:
                status = f"[af.alert]FAIL ({run.error})[/af.alert]"
            metrics_str = (
                ", ".join(f"{k}: {v:.4f}" for k, v in run.metrics.items())
                if run.metrics else "—"
            )
            detail_table.add_row(
                str(run.experiment_index + 1),
                f"UNIT-{unit_idx + 1:02d}",
                status,
                metrics_str,
            )
        console.print(detail_table)
        console.print()
