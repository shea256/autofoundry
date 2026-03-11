"""Tests for the GPU planner module."""

from unittest.mock import MagicMock, patch

from autofoundry.models import GpuOffer, ProviderName, ProvisioningPlan
from autofoundry.planner import query_all_offers, recommend_plan


def _make_offer(
    provider: ProviderName = ProviderName.RUNPOD,
    gpu_type: str = "H100",
    price: float = 2.50,
    offer_id: str = "offer-1",
) -> GpuOffer:
    return GpuOffer(
        provider=provider,
        offer_id=offer_id,
        gpu_type=gpu_type,
        gpu_count=1,
        gpu_ram_gb=80,
        price_per_hour=price,
        region="US",
        availability=3,
    )


class TestRecommendPlan:
    def test_empty_offers(self) -> None:
        assert recommend_plan([], 4) == []

    def test_picks_cheapest(self) -> None:
        offers = [
            _make_offer(price=3.00, offer_id="expensive"),
            _make_offer(price=1.50, offer_id="cheap"),
        ]
        # Offers should be pre-sorted, but recommend_plan picks first
        offers.sort(key=lambda o: o.price_per_hour)
        result = recommend_plan(offers, 4)
        assert len(result) == 1
        assert result[0][0].offer_id == "cheap"
        assert result[0][1] == 1


class TestQueryAllOffers:
    def test_aggregates_from_multiple_providers(self) -> None:
        runpod_offers = [_make_offer(ProviderName.RUNPOD, price=2.50)]
        pi_offers = [_make_offer(ProviderName.PRIMEINTELLECT, price=2.00)]

        mock_config = MagicMock()
        mock_config.configured_providers = [
            ProviderName.RUNPOD,
            ProviderName.PRIMEINTELLECT,
        ]
        mock_config.api_keys = {
            ProviderName.RUNPOD: "key1",
            ProviderName.PRIMEINTELLECT: "key2",
        }

        def mock_get_provider(name, key):
            mock = MagicMock()
            if name == ProviderName.RUNPOD:
                mock.list_gpu_offers.return_value = runpod_offers
            else:
                mock.list_gpu_offers.return_value = pi_offers
            return mock

        with patch("autofoundry.planner.get_provider", side_effect=mock_get_provider):
            offers = query_all_offers(mock_config, "H100")

        assert len(offers) == 2
        # Should be sorted by price
        assert offers[0].price_per_hour <= offers[1].price_per_hour

    def test_handles_provider_error_gracefully(self) -> None:
        mock_config = MagicMock()
        mock_config.configured_providers = [ProviderName.RUNPOD]
        mock_config.api_keys = {ProviderName.RUNPOD: "key1"}

        def mock_get_provider(name, key):
            mock = MagicMock()
            mock.list_gpu_offers.side_effect = RuntimeError("API down")
            return mock

        with patch("autofoundry.planner.get_provider", side_effect=mock_get_provider):
            offers = query_all_offers(mock_config, "H100")

        assert offers == []


class TestProvisioningPlan:
    def test_total_instances(self) -> None:
        plan = ProvisioningPlan(
            offers=[
                (_make_offer(price=2.00), 2),
                (_make_offer(price=3.00), 1),
            ],
            total_experiments=8,
        )
        assert plan.total_instances == 3

    def test_estimated_cost(self) -> None:
        plan = ProvisioningPlan(
            offers=[
                (_make_offer(price=2.00), 2),
                (_make_offer(price=3.00), 1),
            ],
            total_experiments=8,
        )
        assert plan.estimated_cost_per_hour == 7.00
