"""Tests for GPU tier filtering and name matching."""

from autofoundry.gpu_filter import (
    DEFAULT_MIN_VRAM,
    DEFAULT_SEGMENT,
    GPU_TIERS,
    GpuQuery,
    filter_by_vram,
    gpu_name_matches,
    resolve_query,
    tier_for_gpu,
)
from autofoundry.models import GpuOffer, ProviderName


def _offer(gpu_type: str = "H100", gpu_ram_gb: float = 80.0) -> GpuOffer:
    return GpuOffer(
        provider=ProviderName.RUNPOD,
        offer_id="test",
        gpu_type=gpu_type,
        gpu_count=1,
        gpu_ram_gb=gpu_ram_gb,
        price_per_hour=1.0,
        region="US",
        availability=1,
    )


class TestGpuTiers:
    def test_seven_tiers_defined(self):
        assert len(GPU_TIERS) == 7

    def test_defaults(self):
        assert DEFAULT_SEGMENT == "datacenter"
        assert DEFAULT_MIN_VRAM == 80.0

    def test_all_tiers_have_patterns(self):
        for t in GPU_TIERS:
            assert len(t.gpu_patterns) > 0, f"Tier {t.name} has no patterns"

    def test_categories(self):
        categories = {t.category for t in GPU_TIERS}
        assert categories == {"consumer", "workstation", "datacenter"}

    def test_tier_names_unique(self):
        names = [t.name for t in GPU_TIERS]
        assert len(names) == len(set(names))


class TestTierForGpu:
    def test_h100_80gb(self):
        t = tier_for_gpu("H100 SXM", 80)
        assert t is not None
        assert t.name == "datacenter-80gb+"

    def test_a100_80gb(self):
        t = tier_for_gpu("A100 80GB PCIe", 80)
        assert t is not None
        assert t.name == "datacenter-80gb+"

    def test_a100_40gb(self):
        t = tier_for_gpu("A100 40GB", 40)
        assert t is not None
        assert t.name == "datacenter-40gb+"

    def test_a100_vram_disambiguation(self):
        """A100 pattern appears in both 40gb+ and 80gb+; VRAM range separates them."""
        t40 = tier_for_gpu("A100", 40)
        t80 = tier_for_gpu("A100", 80)
        assert t40.name == "datacenter-40gb+"
        assert t80.name == "datacenter-80gb+"

    def test_l4(self):
        t = tier_for_gpu("L4", 24)
        assert t is not None
        assert t.name == "datacenter-24gb+"

    def test_l40_matches_datacenter_40gb(self):
        """L40 pattern should match L40S via prefix matching."""
        t = tier_for_gpu("L40S", 48)
        assert t is not None
        assert t.name == "datacenter-40gb+"

    def test_h200(self):
        t = tier_for_gpu("H200 SXM", 141)
        assert t is not None
        assert t.name == "datacenter-140gb+"

    def test_gh200(self):
        t = tier_for_gpu("GH200", 144)
        assert t is not None
        assert t.name == "datacenter-140gb+"

    def test_rtx_4090(self):
        t = tier_for_gpu("RTX 4090", 24)
        assert t is not None
        assert t.name == "consumer-16gb+"

    def test_rtx_a6000(self):
        t = tier_for_gpu("RTX A6000", 48)
        assert t is not None
        assert t.name == "workstation-48gb+"

    def test_rtx_pro_6000(self):
        """RTX PRO 6000 (all variants) should be workstation."""
        t = tier_for_gpu("RTX PRO 6000", 96)
        assert t is not None
        assert t.name == "workstation-48gb+"

    def test_rtx_pro_6000_wk(self):
        t = tier_for_gpu("RTX PRO 6000 WK", 48)
        assert t is not None
        assert t.name == "workstation-48gb+"

    def test_unknown_gpu(self):
        t = tier_for_gpu("Unknown GPU X", 32)
        assert t is None

    def test_b200(self):
        t = tier_for_gpu("B200", 192)
        assert t is not None
        assert t.name == "datacenter-140gb+"


class TestGpuNameMatches:
    def test_exact_match(self):
        assert gpu_name_matches("H100", "H100")

    def test_prefix_match(self):
        assert gpu_name_matches("H100", "H100 SXM")

    def test_no_substring_match(self):
        """H100 should NOT match GH100."""
        assert not gpu_name_matches("H100", "GH100")

    def test_h200_matches_h200_sxm(self):
        assert gpu_name_matches("H200", "H200 SXM")

    def test_empty_query_matches_all(self):
        assert gpu_name_matches("", "H100 SXM")

    def test_case_insensitive(self):
        assert gpu_name_matches("h100", "H100 SXM")


class TestFilterByVram:
    def test_filter_min(self):
        offers = [_offer(gpu_ram_gb=24), _offer(gpu_ram_gb=80), _offer(gpu_ram_gb=16)]
        result = filter_by_vram(offers, vram_min=24)
        assert len(result) == 2

    def test_filter_max(self):
        offers = [_offer(gpu_ram_gb=24), _offer(gpu_ram_gb=80)]
        result = filter_by_vram(offers, vram_max=48)
        assert len(result) == 1
        assert result[0].gpu_ram_gb == 24

    def test_filter_range(self):
        offers = [
            _offer(gpu_ram_gb=16),
            _offer(gpu_ram_gb=80),
            _offer(gpu_ram_gb=141),
        ]
        result = filter_by_vram(offers, vram_min=80, vram_max=140)
        assert len(result) == 1
        assert result[0].gpu_ram_gb == 80


class TestResolveQuery:
    def test_gpu_type_takes_priority(self):
        q = resolve_query(gpu_type="H100", segment="datacenter", vram_min=40)
        assert q.gpu_type == "H100"
        assert q.segment is None

    def test_segment_with_vram(self):
        q = resolve_query(segment="datacenter", vram_min=80)
        assert q.segment == "datacenter"
        assert q.vram_min == 80
        assert "A100" in q.gpu_patterns
        assert "H100" in q.gpu_patterns

    def test_segment_alone(self):
        q = resolve_query(segment="datacenter")
        assert q.segment == "datacenter"
        assert q.vram_min is None
        # Should include patterns from all datacenter tiers
        assert "L4" in q.gpu_patterns
        assert "H100" in q.gpu_patterns

    def test_vram_alone(self):
        q = resolve_query(vram_min=80)
        assert q.vram_min == 80
        assert q.segment is None
        assert q.gpu_patterns is None

    def test_default_query(self):
        q = resolve_query()
        assert q.segment == "datacenter"
        assert q.vram_min == 80
        assert "A100" in q.gpu_patterns
        assert "H100" in q.gpu_patterns

    def test_custom_defaults(self):
        q = resolve_query(default_segment="workstation", default_min_vram=48)
        assert q.segment == "workstation"
        assert q.vram_min == 48

    def test_segment_filters_patterns(self):
        """Only patterns from matching segment should be included."""
        q = resolve_query(segment="consumer")
        assert q.segment == "consumer"
        assert "RTX 4090" in q.gpu_patterns
        assert "H100" not in q.gpu_patterns

    def test_segment_with_vram_filters_tiers(self):
        """VRAM range should exclude tiers that don't overlap."""
        q = resolve_query(segment="datacenter", vram_min=80)
        # Should not include L4 (24-40GB range) or A40 (40-80GB range)
        assert "L4" not in q.gpu_patterns
        assert "A40" not in q.gpu_patterns


class TestGpuQueryDescription:
    def test_gpu_type_description(self):
        q = GpuQuery(gpu_type="H100")
        assert q.description == "H100"

    def test_segment_description(self):
        q = GpuQuery(segment="datacenter", vram_min=80)
        assert "Datacenter" in q.description
        assert "80GB+" in q.description

    def test_segment_only_description(self):
        q = GpuQuery(segment="datacenter")
        assert q.description == "Datacenter"

    def test_vram_range_description(self):
        q = GpuQuery(vram_min=40, vram_max=100)
        assert "40" in q.description
        assert "100" in q.description

    def test_all_gpus_description(self):
        q = GpuQuery()
        assert q.description == "all GPUs"
