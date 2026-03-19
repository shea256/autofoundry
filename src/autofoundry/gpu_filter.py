"""GPU tier definitions, name matching, and VRAM-based filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass

from autofoundry.models import GpuOffer


@dataclass(frozen=True)
class GpuTier:
    """A GPU tier defined by category, VRAM range, and GPU name patterns."""

    name: str            # e.g. "datacenter-80gb+"
    label: str           # e.g. "Datacenter 80GB+ (A100 80GB, H100)"
    category: str        # "consumer", "workstation", "datacenter"
    vram_min: float      # inclusive lower bound
    vram_max: float      # exclusive upper bound (inf for top tier)
    gpu_patterns: tuple[str, ...]  # patterns for gpu_name_matches()


GPU_TIERS = [
    GpuTier(
        "consumer-16gb+",
        "Consumer 16GB+ (RTX 3090, 4090, 5090)",
        "consumer", 16, float("inf"),
        ("RTX 3090", "RTX 4090", "RTX 5090"),
    ),
    GpuTier(
        "workstation-16gb+",
        "Workstation 16GB+ (RTX 2000/4000 Ada, A4000, A5000)",
        "workstation", 16, 48,
        ("RTX 2000", "RTX 4000", "RTX A4000", "RTX A4500", "RTX A5000", "RTX Pro 4500"),
    ),
    GpuTier(
        "workstation-48gb+",
        "Workstation 48GB+ (RTX 6000 Ada, A6000, RTX PRO 6000)",
        "workstation", 48, float("inf"),
        ("RTX 6000", "RTX A6000", "RTX PRO 6000"),
    ),
    GpuTier(
        "datacenter-24gb+",
        "Datacenter 24GB+ (L4)",
        "datacenter", 24, 40,
        ("L4",),
    ),
    GpuTier(
        "datacenter-40gb+",
        "Datacenter 40GB+ (A40, L40/L40S, A100 40GB)",
        "datacenter", 40, 80,
        ("A40", "L40", "A100"),
    ),
    GpuTier(
        "datacenter-80gb+",
        "Datacenter 80GB+ (A100 80GB, H100)",
        "datacenter", 80, 140,
        ("A100", "H100"),
    ),
    GpuTier(
        "datacenter-140gb+",
        "Datacenter 140GB+ (H200, GH200, B200, B300)",
        "datacenter", 140, float("inf"),
        ("H200", "GH200", "B200", "B300"),
    ),
]

TIER_BY_NAME: dict[str, GpuTier] = {t.name: t for t in GPU_TIERS}

DEFAULT_TIER = "datacenter-80gb+"

# Backward-compat mapping from old VRAM-only tier names
_TIER_MIGRATION: dict[str, str] = {
    "<24gb": "consumer-16gb+",
    "24gb+": "datacenter-24gb+",
    "48gb+": "workstation-48gb+",
    "80gb+": "datacenter-80gb+",
    "140gb+": "datacenter-140gb+",
}


@dataclass
class GpuQuery:
    """Encapsulates GPU filtering intent from CLI args."""

    gpu_type: str | None = None       # explicit GPU name filter (e.g. "H100")
    vram_min: float | None = None
    vram_max: float | None = None
    tier: str | None = None           # tier name like "datacenter-80gb+"
    gpu_patterns: tuple[str, ...] | None = None  # patterns from tier
    single_gpu: bool = True           # only show single-GPU instances

    @property
    def description(self) -> str:
        """Human-readable description of this query."""
        if self.gpu_type:
            return self.gpu_type
        if self.tier:
            t = TIER_BY_NAME.get(self.tier)
            return t.label if t else self.tier
        if self.vram_min is not None or self.vram_max is not None:
            lo = f"{self.vram_min:.0f}" if self.vram_min else "0"
            hi = f"{self.vram_max:.0f}" if self.vram_max else "∞"
            return f"{lo}-{hi} GB VRAM"
        return "all GPUs"


# Token-splitting pattern: split on spaces, parens, dashes, slashes
_TOKEN_SPLIT = re.compile(r"[\s()\-/]+")


def gpu_name_matches(query: str, gpu_name: str) -> bool:
    """Check if a GPU name matches a query using word-boundary matching.

    Tokenizes both query and GPU name. Single-token queries match if any name
    token starts with the query. Multi-token queries match if consecutive name
    tokens start with each query token.

    "H100" matches "H100", "H100 SXM", "H100 NVL" but NOT "GH100".
    "RTX 4090" matches "RTX 4090", "NVIDIA RTX 4090" but NOT "RTX 4080".
    """
    query_upper = query.strip().upper()
    if not query_upper:
        return True

    name_tokens = [t for t in _TOKEN_SPLIT.split(gpu_name.upper()) if t]
    query_tokens = [t for t in _TOKEN_SPLIT.split(query_upper) if t]

    if len(query_tokens) == 1:
        return any(t.startswith(query_tokens[0]) for t in name_tokens)

    # Multi-token: find consecutive name tokens matching query tokens
    for start in range(len(name_tokens) - len(query_tokens) + 1):
        if all(
            name_tokens[start + i].startswith(qt)
            for i, qt in enumerate(query_tokens)
        ):
            return True
    return False


def filter_by_vram(
    offers: list[GpuOffer],
    vram_min: float | None = None,
    vram_max: float | None = None,
) -> list[GpuOffer]:
    """Filter offers by VRAM range (per-GPU, not total)."""
    result = offers
    if vram_min is not None:
        result = [o for o in result if o.gpu_ram_gb >= vram_min]
    if vram_max is not None:
        result = [o for o in result if o.gpu_ram_gb < vram_max]
    return result


def tier_for_name(name: str) -> GpuTier | None:
    """Look up a tier by its name string. Supports old tier names via migration."""
    key = name.lower().strip()
    # Try direct lookup first, then migrate old names
    migrated = _TIER_MIGRATION.get(key, key)
    return TIER_BY_NAME.get(migrated)


def tier_for_gpu(gpu_name: str, vram_gb: float) -> GpuTier | None:
    """Find which tier a GPU belongs to based on name and VRAM."""
    for t in GPU_TIERS:
        if t.vram_min <= vram_gb < t.vram_max:
            if any(gpu_name_matches(pat, gpu_name) for pat in t.gpu_patterns):
                return t
    return None


def resolve_query(
    *,
    gpu_type: str | None = None,
    vram_min: float | None = None,
    vram_max: float | None = None,
    tier: str | None = None,
    default_tier: str = DEFAULT_TIER,
) -> GpuQuery:
    """Convert raw CLI inputs into a GpuQuery.

    Priority: --gpu > --tier > --vram-min/--vram-max > default_tier.
    """
    if gpu_type:
        return GpuQuery(gpu_type=gpu_type)

    if tier:
        t = tier_for_name(tier)
        if t:
            return GpuQuery(
                tier=t.name, vram_min=t.vram_min, vram_max=t.vram_max,
                gpu_patterns=t.gpu_patterns,
            )
        # Unknown tier name — treat as GPU type
        return GpuQuery(gpu_type=tier)

    if vram_min is not None or vram_max is not None:
        return GpuQuery(vram_min=vram_min, vram_max=vram_max)

    # Default: use default tier
    t = tier_for_name(default_tier)
    if t:
        return GpuQuery(
            tier=t.name, vram_min=t.vram_min, vram_max=t.vram_max,
            gpu_patterns=t.gpu_patterns,
        )

    return GpuQuery(
        tier=DEFAULT_TIER, vram_min=80, vram_max=140,
        gpu_patterns=("A100", "H100"),
    )
