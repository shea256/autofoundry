"""SQLite-backed session persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from autofoundry.config import SESSIONS_DIR
from autofoundry.models import (
    ExperimentResult,
    ExperimentStatus,
    InstanceInfo,
    InstanceStatus,
    ProviderName,
    Session,
    SessionStatus,
    SshConnectionInfo,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session (
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'configuring',
    script_path TEXT NOT NULL DEFAULT '',
    total_experiments INTEGER NOT NULL DEFAULT 0,
    gpu_type TEXT NOT NULL DEFAULT 'H100',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS instances (
    instance_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_instance_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    gpu_type TEXT NOT NULL DEFAULT '',
    gpu_count INTEGER NOT NULL DEFAULT 1,
    price_per_hour REAL NOT NULL DEFAULT 0.0,
    ssh_host TEXT,
    ssh_port INTEGER,
    ssh_username TEXT DEFAULT 'root',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT,
    run_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    completed_at TEXT,
    exit_code INTEGER,
    raw_output TEXT DEFAULT '',
    FOREIGN KEY (instance_id) REFERENCES instances(instance_id)
);

CREATE TABLE IF NOT EXISTS results (
    experiment_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (experiment_id, key),
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    data TEXT DEFAULT '{}'
);
"""


class SessionStore:
    """SQLite-backed store for a single autofoundry session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = SESSIONS_DIR / f"{session_id}.db"
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- Session ---

    def create_session(self, session: Session) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO session "
            "(session_id, status, script_path, total_experiments, gpu_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session.session_id,
                session.status.value,
                session.script_path,
                session.total_experiments,
                session.gpu_type,
                session.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def update_session_status(self, status: SessionStatus) -> None:
        self._conn.execute(
            "UPDATE session SET status = ? WHERE session_id = ?",
            (status.value, self.session_id),
        )
        self._conn.commit()

    def get_session(self) -> Session | None:
        row = self._conn.execute(
            "SELECT * FROM session WHERE session_id = ?", (self.session_id,)
        ).fetchone()
        if not row:
            return None
        return Session(
            session_id=row["session_id"],
            status=SessionStatus(row["status"]),
            script_path=row["script_path"],
            total_experiments=row["total_experiments"],
            gpu_type=row["gpu_type"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # --- Instances ---

    def add_instance(self, info: InstanceInfo) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO instances "
            "(instance_id, provider, provider_instance_id, name, status, gpu_type, gpu_count, "
            "price_per_hour, ssh_host, ssh_port, ssh_username, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                info.instance_id,
                info.provider.value,
                info.instance_id,
                info.name,
                info.status.value,
                info.gpu_type,
                info.gpu_count,
                info.price_per_hour,
                info.ssh.host if info.ssh else None,
                info.ssh.port if info.ssh else None,
                info.ssh.username if info.ssh else "root",
                info.created_at.isoformat() if info.created_at else None,
            ),
        )
        self._conn.commit()

    def update_instance_status(self, instance_id: str, status: InstanceStatus) -> None:
        self._conn.execute(
            "UPDATE instances SET status = ? WHERE instance_id = ?",
            (status.value, instance_id),
        )
        self._conn.commit()

    def update_instance_ssh(self, instance_id: str, ssh: SshConnectionInfo) -> None:
        self._conn.execute(
            "UPDATE instances SET ssh_host = ?, ssh_port = ?, ssh_username = ? "
            "WHERE instance_id = ?",
            (ssh.host, ssh.port, ssh.username, instance_id),
        )
        self._conn.commit()

    def get_instances(self) -> list[InstanceInfo]:
        rows = self._conn.execute("SELECT * FROM instances").fetchall()
        result = []
        for row in rows:
            ssh = None
            if row["ssh_host"]:
                ssh = SshConnectionInfo(
                    host=row["ssh_host"],
                    port=row["ssh_port"] or 22,
                    username=row["ssh_username"] or "root",
                )
            result.append(InstanceInfo(
                provider=ProviderName(row["provider"]),
                instance_id=row["instance_id"],
                name=row["name"],
                status=InstanceStatus(row["status"]),
                gpu_type=row["gpu_type"],
                gpu_count=row["gpu_count"],
                price_per_hour=row["price_per_hour"],
                ssh=ssh,
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            ))
        return result

    # --- Experiments ---

    def create_experiments(self, count: int) -> list[int]:
        """Create `count` pending experiments. Returns their IDs."""
        ids = []
        for i in range(count):
            cursor = self._conn.execute(
                "INSERT INTO experiments (run_index, status) VALUES (?, ?)",
                (i, ExperimentStatus.PENDING.value),
            )
            ids.append(cursor.lastrowid)
        self._conn.commit()
        return ids

    def assign_experiment(self, experiment_id: int, instance_id: str) -> None:
        self._conn.execute(
            "UPDATE experiments SET instance_id = ?, status = ? WHERE experiment_id = ?",
            (instance_id, ExperimentStatus.RUNNING.value, experiment_id),
        )
        self._conn.commit()

    def complete_experiment(
        self,
        experiment_id: int,
        status: ExperimentStatus,
        exit_code: int | None = None,
        raw_output: str = "",
        metrics: dict[str, float] | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE experiments SET status = ?, completed_at = ?, exit_code = ?, raw_output = ? "
            "WHERE experiment_id = ?",
            (status.value, now, exit_code, raw_output, experiment_id),
        )
        if metrics:
            for key, value in metrics.items():
                self._conn.execute(
                    "INSERT OR REPLACE INTO results (experiment_id, key, value) VALUES (?, ?, ?)",
                    (experiment_id, key, value),
                )
        self._conn.commit()

    def get_pending_experiments(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT experiment_id, run_index FROM experiments WHERE status = ?",
            (ExperimentStatus.PENDING.value,),
        ).fetchall()
        return [{"experiment_id": r["experiment_id"], "run_index": r["run_index"]} for r in rows]

    def get_completed_experiments(self) -> list[ExperimentResult]:
        rows = self._conn.execute(
            "SELECT * FROM experiments WHERE status IN (?, ?)",
            (ExperimentStatus.COMPLETED.value, ExperimentStatus.FAILED.value),
        ).fetchall()
        results = []
        for row in rows:
            metric_rows = self._conn.execute(
                "SELECT key, value FROM results WHERE experiment_id = ?",
                (row["experiment_id"],),
            ).fetchall()
            metrics = {r["key"]: r["value"] for r in metric_rows}
            results.append(ExperimentResult(
                experiment_id=row["experiment_id"],
                instance_id=row["instance_id"] or "",
                run_index=row["run_index"],
                status=ExperimentStatus(row["status"]),
                metrics=metrics,
                raw_output=row["raw_output"] or "",
                started_at=(
                    datetime.fromisoformat(row["started_at"]) if row["started_at"] else None
                ),
                completed_at=(
                    datetime.fromisoformat(row["completed_at"])
                    if row["completed_at"]
                    else None
                ),
                exit_code=row["exit_code"],
            ))
        return results

    def get_all_experiments(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM experiments ORDER BY experiment_id").fetchall()
        return [dict(r) for r in rows]

    # --- Events ---

    def log_event(self, event_type: str, data: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO events (timestamp, event_type, data) VALUES (?, ?, ?)",
            (datetime.now().isoformat(), event_type, json.dumps(data or {})),
        )
        self._conn.commit()

    # --- Listing sessions ---

    @staticmethod
    def list_sessions() -> list[str]:
        """List all session IDs from the sessions directory."""
        if not SESSIONS_DIR.exists():
            return []
        return sorted(p.stem for p in SESSIONS_DIR.glob("*.db"))
