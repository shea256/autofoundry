"""NGE-inspired terminal theme for autofoundry."""

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

# EVA-inspired color palette
COLORS = {
    "primary": "#FF6600",      # EVA-00 orange
    "secondary": "#7B2FBE",    # EVA-01 purple
    "alert": "#CC0000",        # warning red
    "success": "#00FF41",      # terminal green
    "muted": "#666666",        # dim text
    "highlight": "#FFD700",    # gold for best results
}

# NGE-inspired terminology
TERMS = {
    "instance": "UNIT",
    "instances": "UNITS",
    "experiment": "SORTIE",
    "experiments": "SORTIES",
    "provisioning": "ACTIVATION SEQUENCE",
    "results": "INSTRUMENTALITY REPORT",
    "session": "OPERATION",
    "dashboard": "COMMAND CENTER",
    "provider": "SUPPLY LINE",
    "planning": "TACTICAL ASSESSMENT",
    "shutdown": "TERMINATION PROTOCOL",
}

THEME = Theme({
    "af.primary": f"bold {COLORS['primary']}",
    "af.secondary": f"bold {COLORS['secondary']}",
    "af.alert": f"bold {COLORS['alert']}",
    "af.success": f"bold {COLORS['success']}",
    "af.muted": COLORS["muted"],
    "af.highlight": f"bold {COLORS['highlight']}",
    "af.header": f"bold {COLORS['primary']}",
    "af.label": f"{COLORS['secondary']}",
})

console = Console(theme=THEME)

BANNER = r"""[af.primary]
    ╔═══════════════════════════════════════════╗
    ║                                           ║
    ║      █████╗ ██╗   ██╗████████╗ ██████╗    ║
    ║     ██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗   ║
    ║     ███████║██║   ██║   ██║   ██║   ██║   ║
    ║     ██╔══██║██║   ██║   ██║   ██║   ██║   ║
    ║     ██║  ██║╚██████╔╝   ██║   ╚██████╔╝   ║
    ║     ╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝    ║
    ║                                           ║
    ║     ███████╗ ██████╗ ██╗   ██╗███╗   ██╗  ║
    ║     ██╔════╝██╔═══██╗██║   ██║████╗  ██║  ║
    ║     █████╗  ██║   ██║██║   ██║██╔██╗ ██║  ║
    ║     ██╔══╝  ██║   ██║██║   ██║██║╚██╗██║  ║
    ║     ██║     ╚██████╔╝╚██████╔╝██║ ╚████║  ║
    ║     ╚═╝      ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝  ║
    ║                                           ║
    ║     ██████╗ ██████╗ ██╗   ██╗              ║
    ║     ██╔══██╗██╔══██╗╚██╗ ██╔╝              ║
    ║     ██║  ██║██████╔╝ ╚████╔╝               ║
    ║     ██║  ██║██╔══██╗  ╚██╔╝                ║
    ║     ██████╔╝██║  ██║   ██║                 ║
    ║     ╚═════╝ ╚═╝  ╚═╝   ╚═╝                 ║
    ║                                           ║
    ╚═══════════════════════════════════════════╝
[/af.primary]"""

def print_banner(version: str = "0.1.0", compact: bool = True) -> None:
    """Print the startup banner."""
    if compact:
        console.print()
        console.print(Panel(
            f"[af.primary]A U T O F O U N D R Y   v{version}\n"
            f"GPU Experiment Orchestration Engine[/af.primary]",
            border_style=COLORS["primary"],
            padding=(0, 2),
            expand=True,
        ))
    else:
        console.print()
        console.print(Panel(
            BANNER.strip(),
            border_style=COLORS["primary"],
            padding=(0, 2),
            expand=True,
            subtitle=f"[af.muted]v{version} — GPU Experiment Orchestration Engine[/af.muted]",
        ))


def print_header(text: str) -> None:
    """Print a section header in NGE style."""
    console.print()
    console.print(Panel(
        f"[af.primary]{text}[/af.primary]",
        border_style=COLORS["primary"],
        padding=(0, 2),
        expand=True,
    ))


def print_status(label: str, value: str, style: str = "af.success") -> None:
    """Print a status line."""
    console.print(f"  [af.label]{label}:[/af.label] [{style}]{value}[/{style}]")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"  [af.alert]ERROR:[/af.alert] {message}")


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"  [af.success]OK:[/af.success] {message}")


def make_table(title: str, columns: list[tuple[str, str]]) -> Table:
    """Create a themed table.

    Args:
        title: Table title.
        columns: List of (name, style) tuples.
    """
    table = Table(
        title=f"[af.primary]{title}[/af.primary]",
        border_style=COLORS["primary"],
        header_style="af.secondary",
        show_lines=True,
        box=box.SIMPLE_HEAVY,
    )
    for name, style in columns:
        table.add_column(name, style=style)
    return table
