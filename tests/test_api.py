"""Agent API contracts: no UI, no secrets, no live resources."""

import asyncio
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from autofoundry.api import ApiError, Autofoundry, GpuQuery, ProviderName, run_host_script
from autofoundry.models import GpuOffer, InstanceInfo, InstanceStatus, SshConnectionInfo


@pytest.fixture
def offer():
    return GpuOffer(
        provider="lambdalabs",
        offer_id="a100-80-2",
        gpu_type="A100 80GB",
        gpu_count=2,
        gpu_ram_gb=80,
        price_per_hour=4,
        region="us-east-1",
        metadata={"region_name": "us-east-1"},
    )


@pytest.fixture
def instance():
    return InstanceInfo(
        provider="lambdalabs",
        instance_id="host-exact-id",
        name="af-test",
        status=InstanceStatus.RUNNING,
        gpu_type="A100 80GB",
        gpu_count=2,
        ssh=SshConnectionInfo(host="example.invalid", port=2222, username="ubuntu"),
    )


def test_import_is_silent_and_does_not_load_ui_or_environment_files():
    code = """
import sys
import autofoundry.api
for name in ('autofoundry.cli', 'autofoundry.modal_cli', 'autofoundry.theme',
             'autofoundry.config', 'autofoundry.executor', 'dotenv', 'modal'):
    assert name not in sys.modules, name
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_env_credentials_are_masked_and_modal_rejected(monkeypatch):
    monkeypatch.setenv("LAMBDALABS_API_KEY", "fake-secret")
    client = Autofoundry.from_env()
    assert "fake-secret" not in repr(client)
    assert "fake-secret" not in repr(client._credentials)
    with pytest.raises(ApiError, match="official Modal"):
        Autofoundry({ProviderName.MODAL: "fake-secret"})


def test_discovery_retains_constraints_and_provider_errors(offer, monkeypatch, capsys):
    client = Autofoundry({ProviderName.LAMBDALABS: "fake-secret"})
    backend = Mock()
    backend.list_gpu_offers.return_value = [
        offer,
        offer.model_copy(update={"gpu_ram_gb": 40}),
        offer.model_copy(update={"gpu_type": "H100"}),
    ]

    def get(name):
        if name == ProviderName.RUNPOD:
            raise RuntimeError("fake-secret must not escape")
        return backend

    monkeypatch.setattr(client, "_provider", get)
    inventory = client.discover(
        GpuQuery(gpu_type="A100", vram_min=80, single_gpu=False),
        providers=[ProviderName.LAMBDALABS, ProviderName.RUNPOD],
    )
    assert inventory.offers == [offer]
    assert inventory.providers[1].error == "discovery_failed"
    assert "fake-secret" not in inventory.model_dump_json()
    assert capsys.readouterr().out == ""
    assert client.discover(providers=[]).providers == []


def test_modal_planning_is_local_and_explicit(monkeypatch):
    monkeypatch.setattr(
        "autofoundry.providers.modal.ModalProvider._sdk", Mock(side_effect=AssertionError("no SDK"))
    )
    client = Autofoundry()
    discovery = client.discover(
        GpuQuery(gpu_type="A100", vram_min=80), providers=[ProviderName.MODAL]
    )
    assert all(o.availability is None for o in discovery.offers)
    spec = client.plan_modal(
        GpuQuery(gpu_type="A100", vram_min=80),
        script="train.sh",
        gpu_count=3,
        region="us-west",
        memory_mib=8192,
    )
    assert spec.selector == "A100-80GB:3"
    assert spec.region == "us-west" and spec.memory_mib == 8192
    assert spec.estimate()["region_multiplier"] == 1.75
    assert spec.estimate()["total_cost"] is None


def test_host_plan_preserves_native_metadata_and_has_no_side_effects(offer, monkeypatch):
    monkeypatch.setattr("autofoundry.api.get_provider", Mock(side_effect=AssertionError("no API")))
    plan = Autofoundry.plan_host(offer, name="af-test", ssh_public_key="ssh-ed25519 public")
    assert plan.config.gpu_count == 2
    assert plan.config.metadata == {"region_name": "us-east-1"}
    assert plan.config.offer_id == offer.offer_id
    assert plan.config.image == ""  # Lambda is bare metal.
    assert "fake-secret" not in plan.model_dump_json()
    with pytest.raises(ApiError):
        Autofoundry.plan_host(
            offer.model_copy(update={"provider": ProviderName.MODAL}),
            name="af-test",
            ssh_public_key="public",
        )


def test_host_create_once_and_redacts_ambiguous_failure(offer, monkeypatch):
    client = Autofoundry({ProviderName.LAMBDALABS: "fake-secret"})
    backend = Mock()
    backend.create_instance.side_effect = RuntimeError("authorization: fake-secret")
    monkeypatch.setattr(client, "_provider", lambda name: backend)
    plan = client.plan_host(offer, name="af-unique", ssh_public_key="public")
    with pytest.raises(ApiError) as error:
        client.create_host(plan)
    assert error.value.code == "creation_unconfirmed"
    assert "fake-secret" not in str(error.value)
    backend.create_instance.assert_called_once_with(plan.config)
    plan.config.gpu_count = 1
    with pytest.raises(ApiError) as error:
        client.create_host(plan)
    assert error.value.code == "plan_changed"
    backend.create_instance.assert_called_once()


def test_host_readiness_and_cleanup_are_separate(instance, monkeypatch):
    client = Autofoundry()
    backend = Mock()
    backend.get_instance.return_value = instance
    monkeypatch.setattr(client, "_provider", lambda name: backend)
    assert client.wait_host(instance) == instance
    backend.wait_until_ready.assert_not_called()  # Existing adapter can print terminal UI.
    backend.delete_instance.assert_not_called()
    client.terminate_host(instance.provider, instance.instance_id)
    backend.delete_instance.assert_called_once_with("host-exact-id")
    backend.get_instance.return_value = instance.model_copy(update={"status": InstanceStatus.ERROR})
    with pytest.raises(ApiError) as error:
        client.wait_host(instance)
    assert error.value.code == "host_unavailable"
    backend.delete_instance.assert_called_once()


def test_missing_credentials_and_cleanup_failure_are_safe(instance, monkeypatch):
    client = Autofoundry()
    with pytest.raises(ApiError) as error:
        client.get_host(instance.provider, instance.instance_id)
    assert error.value.code == "missing_credentials"
    backend = Mock()
    backend.delete_instance.side_effect = RuntimeError("private-provider-body")
    monkeypatch.setattr(client, "_provider", lambda name: backend)
    with pytest.raises(ApiError) as error:
        client.terminate_host(instance.provider, instance.instance_id)
    assert error.value.code == "cleanup_unconfirmed"
    assert "private-provider-body" not in str(error.value)


class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def transport(tmp_path, monkeypatch):
    script = tmp_path / "train.sh"
    script.write_text("echo hello")
    process = SimpleNamespace(
        stdout=SimpleNamespace(read=AsyncMock(side_effect=["hello\n---\nloss: 0.25\n", ""])),
        stderr=SimpleNamespace(read=AsyncMock(return_value="")),
        wait_closed=AsyncMock(),
        exit_status=0,
        terminate=Mock(),
    )
    sftp = SimpleNamespace(put=AsyncMock(), remove=AsyncMock())
    connection = SimpleNamespace(
        start_sftp_client=Mock(return_value=AsyncContext(sftp)),
        create_process=Mock(return_value=AsyncContext(process)),
    )
    connect = Mock(return_value=AsyncContext(connection))
    monkeypatch.setattr("asyncssh.connect", connect)
    return SimpleNamespace(
        script=script,
        process=process,
        sftp=sftp,
        connection=connection,
        connect=connect,
        directory=tmp_path / "result",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code,status", [(0, "completed"), (7, "failed")])
async def test_script_results_without_prompts_or_environment(
    instance, transport, monkeypatch, capsys, exit_code, status
):
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "must-not-forward")
    transport.process.exit_status = exit_code
    result = await run_host_script(
        instance,
        transport.script,
        ssh_key_path="/tmp/key",
        directory=transport.directory,
        known_hosts="/tmp/known-hosts",
    )
    assert result.status == status and result.exit_code == exit_code
    assert result.metrics == {"loss": 0.25}
    assert (transport.directory / "output.log").read_text().startswith("hello")
    assert json.loads((transport.directory / "result.json").read_text())["exit_code"] == exit_code
    kwargs = transport.connect.call_args.kwargs
    assert kwargs["known_hosts"] == "/tmp/known-hosts"
    assert kwargs["port"] == 2222 and kwargs["config"] is None
    assert kwargs["password_auth"] is False
    assert transport.connection.create_process.call_args.kwargs["env"] == {}
    assert "must-not-forward" not in repr(transport.connection.create_process.call_args)
    transport.sftp.remove.assert_awaited_once_with(transport.sftp.put.call_args.args[1])
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_ssh_failure_is_redacted_and_saved(instance, transport):
    transport.connect.side_effect = RuntimeError("must-not-print-credential")
    result = await run_host_script(
        instance, transport.script, ssh_key_path="/tmp/key", directory=transport.directory
    )
    assert result.status == "failed" and result.error == "execution_failed_or_timed_out"
    assert "must-not-print-credential" not in (transport.directory / "result.json").read_text()


@pytest.mark.asyncio
async def test_script_timeout_signals_process_and_preserves_result(instance, transport):
    async def stalled(*args):
        await asyncio.sleep(10)

    transport.process.exit_status = None
    transport.process.stdout.read.side_effect = stalled
    result = await run_host_script(
        instance,
        transport.script,
        ssh_key_path="/tmp/key",
        directory=transport.directory,
        timeout=0.01,
    )
    assert result.status == "failed" and result.exit_code is None
    transport.process.terminate.assert_called_once()
    assert (transport.directory / "result.json").exists()


@pytest.mark.asyncio
async def test_modal_api_preserves_job_and_cleanup_records(tmp_path, monkeypatch):
    backend = SimpleNamespace(
        run_job=AsyncMock(return_value={"status": "failed", "cleanup": "unconfirmed"}),
        cleanup_job=AsyncMock(),
    )
    monkeypatch.setattr("autofoundry.api.ModalProvider", lambda: backend)
    client = Autofoundry()
    spec = client.plan_modal(GpuQuery(gpu_type="H100"), script="train.sh")
    result = await client.run_modal(spec, tmp_path / "job")
    assert result == {"status": "failed", "cleanup": "unconfirmed"}
    await client.cleanup_modal(tmp_path / "job")
    backend.cleanup_job.assert_awaited_once_with(tmp_path / "job")
