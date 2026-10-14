"""Offline Modal contracts. No real SDK authentication or remote operations."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from autofoundry.cli import app
from autofoundry.config import Config
from autofoundry.gpu_filter import GpuQuery
from autofoundry.models import GpuOffer, ProviderName
from autofoundry.planner import query_all_offers
from autofoundry.providers import get_provider
from autofoundry.providers.base import CloudProvider, ServerlessProvider
from autofoundry.providers.modal import (
    ModalError,
    ModalJobSpec,
    ModalProvider,
    select_offer,
    verify_hardware,
)


def method(value=None, error=None):
    return SimpleNamespace(aio=AsyncMock(return_value=value, side_effect=error))


class Stream:
    def __init__(self, text):
        self.text = text
        self.read = method(text)

    async def __aiter__(self):
        for line in self.text.splitlines(keepends=True):
            yield line


def process(text, code=0):
    return SimpleNamespace(stdout=Stream(text), stderr=Stream(""), wait=method(), returncode=code)


@pytest.fixture
def fake(tmp_path):
    script = tmp_path / "train.sh"
    script.write_text("echo experiment")
    probe = process("NVIDIA H100 80GB HBM3, 81559 MiB\n")
    workload = process("training\n---\nloss: 0.25\naccuracy: 98%\n")
    sandbox = SimpleNamespace(
        object_id="sb-test",
        exec=method(),
        terminate=method(),
        get_tags=method(),
        filesystem=SimpleNamespace(
            make_directory=method(), copy_from_local=method(), copy_to_local=method()
        ),
    )
    sandbox.exec.aio.side_effect = [probe, workload]
    volume = SimpleNamespace(hydrate=method())
    sdk = SimpleNamespace(
        Client=SimpleNamespace(from_env=method(object())),
        App=SimpleNamespace(lookup=method(object())),
        Sandbox=SimpleNamespace(
            create=method(sandbox), from_id=method(sandbox), from_name=method(sandbox)
        ),
        Volume=SimpleNamespace(from_name=Mock(return_value=volume)),
        Image=SimpleNamespace(from_registry=Mock(return_value=object())),
    )
    return SimpleNamespace(
        sdk=sdk,
        sandbox=sandbox,
        workload=workload,
        probe=probe,
        spec=ModalJobSpec(script=str(script)),
        directory=tmp_path / "job",
    )


def test_catalog_never_imports_sdk_and_is_not_host(monkeypatch):
    monkeypatch.setattr("importlib.import_module", Mock(side_effect=AssertionError("no SDK")))
    provider = get_provider(ProviderName.MODAL)
    offers = provider.list_gpu_offers()
    assert offers and all(o.availability is None for o in offers)
    assert all(
        o.execution_kind == "serverless" and o.price_basis == "catalog_compute" for o in offers
    )
    assert isinstance(provider, ServerlessProvider)
    assert not isinstance(provider, CloudProvider)
    with pytest.raises(ValueError, match="official Modal"):
        get_provider(ProviderName.MODAL, "must-not-be-used")


def test_gpu_family_memory_count_and_strict_selectors():
    assert {o.gpu_type for o in ModalProvider().list_gpu_offers("L4")} == {"L4"}
    assert {o.gpu_type for o in ModalProvider().list_gpu_offers("A100")} == {
        "A100-40GB",
        "A100-80GB",
    }
    offer = select_offer(GpuQuery(gpu_type="A100", vram_min=80), 2)
    assert offer.gpu_ram_gb == 80 and offer.gpu_count == 2
    assert offer.offer_id == "A100-80GB:2"
    with pytest.raises(ModalError):
        select_offer(GpuQuery(gpu_type="A100-40GB", vram_min=80), 2)
    assert ModalJobSpec(script="", gpu="H100", gpu_count=4).selector == "H100!:4"
    for gpu in ("A100", "B200+", "H100!", "H100,A100-80GB"):
        with pytest.raises(ValidationError):
            ModalJobSpec(script="", gpu=gpu)
    with pytest.raises(ValidationError):
        ModalJobSpec(script="", gpu="A10", gpu_count=8)


@pytest.mark.parametrize(
    "region,multiplier", [(None, 1), ("us", 1.15), ("us-west", 1.75), ("jp", 1.75)]
)
def test_pricing_units(region, multiplier):
    estimate = ModalJobSpec(
        script="",
        gpu="A100-80GB",
        gpu_count=2,
        cpu=4,
        memory_mib=8192,
        region=region,
        timeout_seconds=1800,
    ).estimate()
    assert estimate["gpu_per_hour"] == pytest.approx(0.000694 * 2 * 3600)
    assert estimate["cpu_per_hour"] == pytest.approx(0.00003942 * 4 * 3600)
    assert estimate["ram_per_hour"] == pytest.approx(0.00000667 * 8 * 3600)
    expected = (0.000694 * 2 + 0.00003942 * 4 + 0.00000667 * 8) * 3600 * multiplier
    assert estimate["compute_per_hour"] == pytest.approx(expected)
    assert estimate["compute_for_timeout"] == pytest.approx(expected / 2)
    assert estimate["volume_per_gib_month"] == 0.09
    assert estimate["egress_per_gib"] == 0.04
    assert estimate["total_cost"] is None


@pytest.mark.parametrize(
    "values",
    [
        dict(region="US-TX-3"),
        dict(cpu=float("nan")),
        dict(timeout_seconds=86401),
        dict(memory_mib=0),
        dict(artifacts=["/etc/passwd"]),
        dict(artifacts=["/workspace/../secret"]),
        dict(artifacts=["/workspace/a/x", "/workspace/b/x"]),
    ],
)
def test_invalid_requests(values):
    with pytest.raises(ValidationError):
        ModalJobSpec(script="", **values)


@pytest.mark.asyncio
async def test_auth_uses_sdk_configuration_without_arguments(fake, monkeypatch):
    monkeypatch.setenv("MODAL_TOKEN_ID", "test-token-id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "test-token-secret")
    monkeypatch.setenv("MODAL_PROFILE", "test-profile")
    assert await ModalProvider(fake.sdk).validate_auth()
    fake.sdk.Client.from_env.aio.assert_awaited_once_with()
    fake.sdk.Sandbox.create.aio.assert_not_awaited()
    fake.sdk.App.lookup.aio.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_failure_is_redacted_and_no_resources(fake):
    fake.sdk.Client.from_env.aio.side_effect = RuntimeError("test-secret must not escape")
    result = await ModalProvider(fake.sdk).run_job(fake.spec, fake.directory)
    assert result["status"] == "failed" and result["cleanup"] == "not_created"
    assert "test-secret" not in (fake.directory / "job.json").read_text()
    assert "authentication failed" in result["error"]
    fake.sdk.App.lookup.aio.assert_not_awaited()
    fake.sdk.Sandbox.create.aio.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifecycle_results_artifacts_volume_region(fake, monkeypatch):
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "never-forward-this")
    fake.spec.region = "us-west"
    fake.spec.volume = "existing-data"
    fake.spec.artifacts = ["/workspace/result.json"]
    result = await ModalProvider(fake.sdk).run_job(fake.spec, fake.directory)
    assert result["status"] == "completed" and result["cleanup"] == "terminated"
    assert result["metrics"] == {"loss": 0.25, "accuracy": 98}
    assert "training" in (fake.directory / "output.log").read_text()
    kwargs = fake.sdk.Sandbox.create.aio.call_args.kwargs
    assert kwargs["gpu"] == "H100!:1"
    assert kwargs["cpu"] == (2, 2) and kwargs["memory"] == (16384, 16384)
    assert kwargs["region"] == "us-west" and kwargs["timeout"] == 3600
    assert kwargs["runtime"] == "gvisor"
    assert "never-forward-this" not in repr(kwargs)
    assert "MODAL_TOKEN_SECRET" not in kwargs["env"]
    fake.sdk.App.lookup.aio.assert_awaited_once()
    assert fake.sdk.App.lookup.aio.call_args.kwargs["create_if_missing"] is False
    fake.sdk.Volume.from_name.assert_called_once_with("existing-data", create_if_missing=False)
    fake.sandbox.filesystem.copy_to_local.aio.assert_awaited_once_with(
        "/workspace/result.json", fake.directory / "artifacts" / "result.json"
    )
    fake.sandbox.terminate.aio.assert_awaited_once_with(wait=True)
    assert json.loads((fake.directory / "job.json").read_text()) == result


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["lookup", "create", "upload", "execute", "download"])
async def test_failures_are_independent_and_cleanup_is_scoped(fake, phase):
    error = RuntimeError("sensitive SDK payload")
    if phase == "lookup":
        fake.sdk.App.lookup.aio.side_effect = error
    elif phase == "create":
        fake.sdk.Sandbox.create.aio.side_effect = error
    elif phase == "upload":
        fake.sandbox.filesystem.copy_from_local.aio.side_effect = error
    elif phase == "execute":
        fake.sandbox.exec.aio.side_effect = error
    else:
        fake.spec.artifacts = ["/workspace/result.json"]
        fake.sandbox.filesystem.copy_to_local.aio.side_effect = error
    result = await ModalProvider(fake.sdk).run_job(fake.spec, fake.directory)
    assert result["status"] == "failed"
    assert "sensitive" not in json.dumps(result)
    assert fake.sandbox.terminate.aio.await_count == int(phase not in ("lookup", "create"))
    if phase == "create":
        assert result["sandbox_id"] is None and result["cleanup"] == "unconfirmed"
    if phase == "download":
        assert result["exit_code"] == 0 and result["metrics"]["loss"] == 0.25


@pytest.mark.asyncio
async def test_nonzero_exit_retained_when_cleanup_fails(fake):
    fake.workload.returncode = 7
    fake.sandbox.terminate.aio.side_effect = RuntimeError("secret cleanup exception")
    result = await ModalProvider(fake.sdk).run_job(fake.spec, fake.directory)
    assert result["exit_code"] == 7 and result["status"] == "failed"
    assert result["cleanup"] == "unconfirmed"
    assert "secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_timeout_and_cancellation_terminate(fake, monkeypatch):
    async def stalled(*args, **kwargs):
        await asyncio.sleep(10)

    fake.sandbox.filesystem.copy_from_local.aio.side_effect = stalled
    fake.spec.timeout_seconds = 1
    result = await ModalProvider(fake.sdk).run_job(fake.spec, fake.directory)
    assert result["status"] == "failed" and result["cleanup"] == "terminated"
    fake.sandbox.terminate.aio.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_records_interruption_and_cleanup(fake):
    fake.sandbox.filesystem.copy_from_local.aio.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await ModalProvider(fake.sdk).run_job(fake.spec, fake.directory)
    record = json.loads((fake.directory / "job.json").read_text())
    assert record["status"] == "interrupted" and record["cleanup"] == "terminated"


@pytest.mark.asyncio
async def test_cleanup_timeout_is_bounded(fake, monkeypatch):
    async def stalled(**kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr("autofoundry.providers.modal.CLEANUP_TIMEOUT", 0.01)
    fake.sandbox.terminate.aio.side_effect = stalled
    result = await ModalProvider(fake.sdk).run_job(fake.spec, fake.directory)
    assert result["status"] == "completed" and result["cleanup"] == "unconfirmed"


@pytest.mark.asyncio
async def test_cleanup_recovery_checks_ownership_and_exact_name(fake):
    provider = ModalProvider(fake.sdk)
    fake.sdk.Sandbox.create.aio.side_effect = TimeoutError()
    record = await provider.run_job(fake.spec, fake.directory)
    fake.sandbox.get_tags.aio.return_value = {"autofoundry_job": "someone-else"}
    with pytest.raises(ModalError, match="cleanup unconfirmed"):
        await provider.cleanup_job(fake.directory)
    fake.sandbox.terminate.aio.assert_not_awaited()
    fake.sandbox.get_tags.aio.return_value = {"autofoundry_job": record["job_id"]}
    await provider.cleanup_job(fake.directory)
    args = fake.sdk.Sandbox.from_name.aio.call_args.args
    assert args == ("autofoundry", record["job_id"])
    fake.sandbox.terminate.aio.assert_awaited_once_with(wait=True)
    await provider.cleanup_job(fake.directory)  # idempotent; no second termination
    fake.sandbox.terminate.aio.assert_awaited_once()


@pytest.mark.parametrize(
    "hardware",
    [
        "NVIDIA H200, 143771 MiB\n",
        "NVIDIA H100, 40960 MiB\n",
        "garbage\n",
        "NVIDIA H100, 81559 MiB\n" * 2,
    ],
)
def test_hardware_mismatch_rejected(fake, hardware):
    with pytest.raises(ModalError):
        verify_hardware(fake.spec, hardware)


def test_catalog_failure_does_not_hide_host_offers(monkeypatch):
    config = Config()
    config.api_keys[ProviderName.RUNPOD] = "fake"
    offer = GpuOffer(
        provider="runpod",
        offer_id="1",
        gpu_type="H100",
        gpu_count=1,
        gpu_ram_gb=80,
        price_per_hour=3,
    )

    def provider(name, *args, **kwargs):
        if name == ProviderName.MODAL:
            raise RuntimeError("catalog failed")
        return SimpleNamespace(list_gpu_offers=lambda gpu: [offer])

    monkeypatch.setattr("autofoundry.planner.get_provider", provider)
    assert query_all_offers(config, GpuQuery(gpu_type="H100"), include_serverless=True) == [offer]


def test_host_failure_does_not_hide_catalog_and_host_planning_excludes_modal(monkeypatch):
    config = Config()
    config.api_keys[ProviderName.RUNPOD] = "fake"

    def provider(name, *args, **kwargs):
        if name == ProviderName.MODAL:
            return ModalProvider()
        raise RuntimeError("host unavailable")

    monkeypatch.setattr("autofoundry.planner.get_provider", provider)
    offers = query_all_offers(config, GpuQuery(gpu_type="H100"), include_serverless=True)
    assert offers and all(o.provider == ProviderName.MODAL for o in offers)
    assert query_all_offers(config, GpuQuery(gpu_type="H100")) == []


def test_cli_inventory_and_dry_run_need_neither_config_nor_credentials(fake, monkeypatch):
    monkeypatch.setattr(
        "autofoundry.cli.Config.load", Mock(side_effect=AssertionError("no config"))
    )
    monkeypatch.setattr(ModalProvider, "_sdk", Mock(side_effect=AssertionError("no SDK")))
    runner = CliRunner()
    result = runner.invoke(
        app, ["inventory", "--provider", "modal", "--gpu", "A100", "--min-vram", "80"]
    )
    assert result.exit_code == 0, result.output
    assert "unknown" in result.output and "40GB" not in result.output
    result = runner.invoke(
        app,
        [
            "modal",
            "run",
            fake.spec.script,
            "--gpu",
            "A100",
            "--min-vram",
            "80",
            "--gpu-count",
            "2",
            "--region",
            "eu",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"gpu": "A100-80GB"' in result.output
    assert '"total_cost": null' in result.output
    assert '"region_multiplier": 1.15' in result.output


def test_run_provider_modal_bypasses_ssh_setup(fake, monkeypatch):
    execute = Mock()
    monkeypatch.setattr("autofoundry.modal_cli.execute_modal", execute)
    monkeypatch.setattr(
        "autofoundry.cli._load_or_setup_config", Mock(side_effect=AssertionError("no SSH config"))
    )
    result = CliRunner().invoke(app, ["run", fake.spec.script, "--provider", "modal", "--auto"])
    assert result.exit_code == 0, result.output
    execute.assert_called_once()


def test_modal_credentials_not_serialized(tmp_path, monkeypatch):
    import autofoundry.config as config_module

    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(config_module, "SESSIONS_DIR", tmp_path / "sessions")
    config = Config()
    config.api_keys[ProviderName.MODAL] = "never-write"
    config.save()
    assert "never-write" not in (tmp_path / "config.toml").read_text()
    assert ProviderName.MODAL not in config.configured_providers
    assert ProviderName.MODAL not in Config.load().api_keys


def test_sdk_public_api_contract_offline(tmp_path, monkeypatch):
    """Check mocks against installed public SDK signatures without authenticating."""
    import inspect

    monkeypatch.setenv("MODAL_CONFIG_PATH", str(tmp_path / "unused.toml"))
    sdk = pytest.importorskip("modal")
    from modal.sandbox_fs import SandboxFilesystem

    create = inspect.signature(sdk.Sandbox.create)
    for parameter in (
        "tags",
        "name",
        "app",
        "cpu",
        "memory",
        "gpu",
        "region",
        "timeout",
        "runtime",
        "volumes",
        "client",
        "verbose",
    ):
        assert parameter in create.parameters
    for api in (
        sdk.Client.from_env,
        sdk.App.lookup,
        sdk.Sandbox.create,
        sdk.Sandbox.exec,
        sdk.Sandbox.from_name,
        sdk.Sandbox.from_id,
        sdk.Sandbox.terminate,
        sdk.Sandbox.get_tags,
        sdk.Volume.hydrate,
        SandboxFilesystem.make_directory,
        SandboxFilesystem.copy_from_local,
        SandboxFilesystem.copy_to_local,
    ):
        assert callable(api.aio)
    assert "create_if_missing" in inspect.signature(sdk.App.lookup).parameters
    assert "create_if_missing" in inspect.signature(sdk.Volume.from_name).parameters
    assert "wait" in inspect.signature(sdk.Sandbox.terminate).parameters


def test_b200_memory_not_overstated_and_arbitrary_documented_counts():
    with pytest.raises(ModalError):
        select_offer(GpuQuery(gpu_type="B200", vram_min=192))
    assert select_offer(GpuQuery(gpu_type="B200"), 3).gpu_ram_gb == 180
    verify_hardware(ModalJobSpec(script="", gpu="B200"), "NVIDIA B200, 183359 MiB\n")


@pytest.mark.asyncio
async def test_hardware_failure_prevents_script(fake):
    fake.probe.stdout = Stream("NVIDIA H200, 143771 MiB\n")
    result = await ModalProvider(fake.sdk).run_job(fake.spec, fake.directory)
    assert result["status"] == "failed"
    assert "controlled comparison" in result["error"]
    fake.sandbox.exec.aio.assert_awaited_once()
    fake.sandbox.terminate.aio.assert_awaited_once()


@pytest.mark.asyncio
async def test_output_cap_preserves_partial_logs(fake, monkeypatch):
    monkeypatch.setattr("autofoundry.providers.modal.MAX_OUTPUT", 10)
    result = await ModalProvider(fake.sdk).run_job(fake.spec, fake.directory)
    assert result["status"] == "failed" and "Output exceeded" in result["error"]
    assert (fake.directory / "output.log").read_text() == "training\n"
    assert result["cleanup"] == "terminated"


def test_instance_up_rejects_modal_before_config(monkeypatch):
    monkeypatch.setattr(
        "autofoundry.cli._load_or_setup_config", Mock(side_effect=AssertionError("no SSH config"))
    )
    result = CliRunner().invoke(app, ["instance", "up", "--provider", "modal", "--auto"])
    assert result.exit_code == 1
    assert "serverless jobs" in result.output


@pytest.mark.parametrize(
    "gpu,hardware", [("T4", "Tesla T4, 15360 MiB\n"), ("A10", "NVIDIA A10, 23028 MiB\n")]
)
def test_hardware_nominal_gb_accounts_for_mib_and_reserved_memory(gpu, hardware):
    verify_hardware(ModalJobSpec(script="", gpu=gpu), hardware)


def test_host_provisioner_rejects_serverless_plan_before_ssh(monkeypatch):
    from autofoundry.models import ProvisioningPlan
    from autofoundry.provisioner import provision_instances

    monkeypatch.setattr(
        "autofoundry.provisioner._read_ssh_public_key", Mock(side_effect=AssertionError("no SSH"))
    )
    plan = ProvisioningPlan(offers=[(ModalProvider().list_gpu_offers("H100")[0], 1)])
    with pytest.raises(ValueError, match="job executor"):
        provision_instances(Config(), plan, "op-test", Mock())
