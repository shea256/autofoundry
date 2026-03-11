"""Tests for session state persistence."""

from pathlib import Path
from unittest.mock import patch

from autofoundry.models import (
    ExperimentStatus,
    InstanceInfo,
    InstanceStatus,
    ProviderName,
    Session,
    SessionStatus,
    SshConnectionInfo,
)
from autofoundry.state import SessionStore


def _make_store(tmp_path: Path) -> SessionStore:
    """Create a SessionStore with a temporary directory."""
    with patch("autofoundry.state.SESSIONS_DIR", tmp_path):
        return SessionStore("test-op-1")


class TestSessionStore:
    def test_create_and_get_session(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        session = Session(session_id="test-op-1", script_path="/tmp/run.sh", total_experiments=4)
        store.create_session(session)

        loaded = store.get_session()
        assert loaded is not None
        assert loaded.session_id == "test-op-1"
        assert loaded.script_path == "/tmp/run.sh"
        assert loaded.total_experiments == 4
        assert loaded.status == SessionStatus.CONFIGURING
        store.close()

    def test_update_session_status(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        session = Session(session_id="test-op-1")
        store.create_session(session)

        store.update_session_status(SessionStatus.RUNNING)
        loaded = store.get_session()
        assert loaded is not None
        assert loaded.status == SessionStatus.RUNNING
        store.close()

    def test_add_and_get_instances(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        session = Session(session_id="test-op-1")
        store.create_session(session)

        instance = InstanceInfo(
            provider=ProviderName.RUNPOD,
            instance_id="pod-123",
            name="af-test-unit01",
            status=InstanceStatus.RUNNING,
            gpu_type="H100",
            gpu_count=1,
            price_per_hour=2.50,
            ssh=SshConnectionInfo(host="1.2.3.4", port=22, username="root"),
        )
        store.add_instance(instance)

        instances = store.get_instances()
        assert len(instances) == 1
        assert instances[0].instance_id == "pod-123"
        assert instances[0].provider == ProviderName.RUNPOD
        assert instances[0].ssh is not None
        assert instances[0].ssh.host == "1.2.3.4"
        store.close()

    def test_create_and_complete_experiments(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        session = Session(session_id="test-op-1")
        store.create_session(session)

        ids = store.create_experiments(4)
        assert len(ids) == 4

        pending = store.get_pending_experiments()
        assert len(pending) == 4

        # Assign and complete one
        store.assign_experiment(ids[0], "pod-123")
        store.complete_experiment(
            ids[0],
            ExperimentStatus.COMPLETED,
            exit_code=0,
            raw_output="val_bpb: 0.99",
            metrics={"val_bpb": 0.99, "mfu_percent": 40.0},
        )

        pending = store.get_pending_experiments()
        assert len(pending) == 3

        completed = store.get_completed_experiments()
        assert len(completed) == 1
        assert completed[0].metrics["val_bpb"] == 0.99
        assert completed[0].metrics["mfu_percent"] == 40.0
        assert completed[0].exit_code == 0
        store.close()

    def test_log_event(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        session = Session(session_id="test-op-1")
        store.create_session(session)

        store.log_event("test_event", {"key": "value"})
        # No assertion needed -- just verify it doesn't raise
        store.close()

    def test_list_sessions(self, tmp_path: Path) -> None:
        with patch("autofoundry.state.SESSIONS_DIR", tmp_path):
            store1 = SessionStore("op-1")
            store2 = SessionStore("op-2")
            store1.close()
            store2.close()

            sessions = SessionStore.list_sessions()
            assert "op-1" in sessions
            assert "op-2" in sessions
