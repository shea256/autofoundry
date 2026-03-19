"""Tests for GPU tier filtering and name matching."""

from autofoundry.gpu_filter import (
    DEFAULT_TIER,
    GPU_TIERS,
    GpuQuery,
    filter_by_vram,
    gpu_name_matches,
    resolve_query,
    tier_for_gpu,
    tier_for_name,
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

    def test_default_tier(self):
        assert DEFAULT_TIER == "datacenter-80gb+"

    def test_all_tiers_have_patterns(self):
        for t in GPU_TIERS:
            assert len(t.gpu_patterns) > 0, f"Tier {t.name} has no patterns"

    def test_categories(self):
        categories = {t.category for t in GPU_TIERS}
        assert categories == {"consumer", "workstation", "datacenter"}

    def test_tier_names_unique(self):
        names = [t.name for t in GPU_TIERS]
        assert len(names) == len(set(names))


class TestTierLookup:
    def test_tier_for_name(self):
        t = tier_for_name("datacenter-80gb+")
        assert t is not None
        assert t.vram_min == 80
        assert t.vram_max == 140

    def test_tier_for_name_case_insensitive(self):
        assert tier_for_name("Datacenter-80GB+") is not None

    def test_tier_for_name_unknown(self):
        assert tier_for_name("999gb+") is None

    def test_old_tier_name_migration(self):
        """Old VRAM-only tier names should resolve to new tiers."""
        assert tier_for_name("80gb+").name == "datacenter-80gb+"
        assert tier_for_name("140gb+").name == "datacenter-140gb+"
        assert tier_for_name("48gb+").name == "workstation-48gb+"
        assert tier_for_name("<24gb").name == "consumer-16gb+"
        assert tier_for_name("24gb+").name == "datacenter-24gb+"


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
        q = resolve_query(gpu_type="H100", tier="datacenter-40gb+")
        assert q.gpu_type == "H100"
        assert q.tier is None

    def test_tier_sets_vram_bounds_and_patterns(self):
        q = resolve_query(tier="datacenter-80gb+")
        assert q.tier == "datacenter-80gb+"
        assert q.vram_min == 80
        assert q.vram_max == 140
        assert q.gpu_patterns == ("A100", "H100")

    def test_unknown_tier_treated_as_gpu_type(self):
        q = resolve_query(tier="RTX4090")
        assert q.gpu_type == "RTX4090"

    def test_explicit_vram_range(self):
        q = resolve_query(vram_min=40, vram_max=100)
        assert q.vram_min == 40
        assert q.vram_max == 100
        assert q.tier is None
        assert q.gpu_patterns is None

    def test_default_tier(self):
        q = resolve_query()
        assert q.tier == "datacenter-80gb+"
        assert q.vram_min == 80
        assert q.vram_max == 140
        assert q.gpu_patterns == ("A100", "H100")

    def test_custom_default_tier(self):
        q = resolve_query(default_tier="datacenter-40gb+")
        assert q.tier == "datacenter-40gb+"
        assert q.vram_min == 40
        assert q.vram_max == 80

    def test_old_tier_name_resolves(self):
        """Old tier names like '80gb+' should still work via migration."""
        q = resolve_query(tier="80gb+")
        assert q.tier == "datacenter-80gb+"
        assert q.gpu_patterns == ("A100", "H100")


class TestGpuQueryDescription:
    def test_gpu_type_description(self):
        q = GpuQuery(gpu_type="H100")
        assert q.description == "H100"

    def test_tier_description(self):
        q = resolve_query(tier="datacenter-80gb+")
        assert "80GB+" in q.description

    def test_vram_range_description(self):
        q = GpuQuery(vram_min=40, vram_max=100)
        assert "40" in q.description
        assert "100" in q.description

    def test_all_gpus_description(self):
        q = GpuQuery()
        assert q.description == "all GPUs"
