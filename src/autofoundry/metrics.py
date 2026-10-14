"""Pure experiment metric parsing shared by CLI and agent APIs."""


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
