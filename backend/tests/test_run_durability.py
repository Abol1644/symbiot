"""Run durability: SQLite persistence, cancellation, and retention."""

import asyncio
from datetime import datetime, timedelta, UTC
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from symbiot import sidecar
from symbiot.run_manager import (
    RunManager,
    RunSession,
    _SCHEMA,
    _spec_hash,
)


def _now_iso(days_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


async def _insert_run(
    db_path: Path,
    run_id: str,
    *,
    status: str = "done",
    project: str = "demo",
    created_at: str | None = None,
    updated_at: str | None = None,
) -> None:
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(_SCHEMA)
        await db.execute(
            "INSERT INTO runs (run_id, project_name, status, created_at, updated_at, spec_hash, checkpoint_thread_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, project, status, created_at or _now_iso(), updated_at or _now_iso(), "h" * 64, run_id),
        )
        await db.commit()


def insert_run(db_path: Path, run_id: str, **kwargs) -> None:
    asyncio.run(_insert_run(db_path, run_id, **kwargs))


def make_manager(tmp_path: Path, name: str = "runs.db") -> RunManager:
    return RunManager(
        db_path=tmp_path / name,
        checkpoint_path=tmp_path / "checkpoints.db",
    )


# ---------------------------------------------------------------------------
# Section 1: SQLite persistence
# ---------------------------------------------------------------------------

def test_create_run_is_visible_in_sqlite(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    raw_spec = "## META\nname: demo-cli | stack: python 3.12\n\n## OBJECTIVE\nx\n"
    session = manager.start({"raw_spec": raw_spec})

    summary = manager.get_run(session.run_id)
    assert summary is not None
    assert summary.project_name == "demo-cli"
    assert summary.spec_hash == _spec_hash(raw_spec)

    events = manager.get_run_events(session.run_id)
    assert any(e.event_type == "metadata" for e in events)


def test_restart_recovers_running_runs_as_interrupted(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    insert_run(db, "run-1", status="running")
    insert_run(db, "run-2", status="done")

    manager = make_manager(tmp_path)
    assert manager.get_run("run-1").status == "interrupted"
    assert manager.get_run("run-2").status == "done"


def test_events_survive_manager_reinit(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    insert_run(db, "run-1", status="done")

    first = make_manager(tmp_path)
    session = RunSession("run-1")
    first.publish(session, "custom", {"agent": "base", "msg": "hello"})
    first.publish(session, "custom", {"agent": "tester", "msg": "ok"})

    second = make_manager(tmp_path)
    events = second.get_run_events("run-1")
    assert len(events) == 2
    assert events[0].event_type == "custom"
    assert events[0].payload == {"agent": "base", "msg": "hello"}
    assert events[1].id > events[0].id


def test_update_run_status_persists(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    insert_run(db, "run-1", status="running")
    manager = make_manager(tmp_path)
    manager.update_run_status("run-1", "failed")
    assert manager.get_run("run-1").status == "failed"


# ---------------------------------------------------------------------------
# Section 2: history endpoints
# ---------------------------------------------------------------------------

@pytest.fixture()
def api(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    monkeypatch.setattr(sidecar, "run_manager", manager)
    client = TestClient(sidecar.app)
    headers = {"Authorization": f"Bearer {sidecar.API_TOKEN}"}
    return client, manager, headers


def test_history_endpoint_returns_runs(api) -> None:
    client, manager, headers = api
    insert_run(manager.db_path, "run-1", project="alpha", created_at=_now_iso(2))
    insert_run(manager.db_path, "run-2", project="beta", created_at=_now_iso(1))

    response = client.get("/api/runs/history", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert [item["run_id"] for item in data] == ["run-2", "run-1"]
    assert data[0]["project_name"] == "beta"
    assert data[0]["status"] == "done"


def test_events_endpoint_replays_from_sqlite(api) -> None:
    client, manager, headers = api
    insert_run(manager.db_path, "run-1", status="done")
    manager.publish(RunSession("run-1"), "custom", {"agent": "base", "msg": "replayed"})

    response = client.get("/api/runs/run-1/events?after_id=0", headers=headers)
    assert response.status_code == 200
    assert "event: custom" in response.text
    assert '"msg":"replayed"' in response.text


def test_events_endpoint_respects_after_id(api) -> None:
    client, manager, headers = api
    insert_run(manager.db_path, "run-1", status="done")
    session = RunSession("run-1")
    first = manager.publish(session, "custom", {"n": 1})
    manager.publish(session, "custom", {"n": 2})

    response = client.get(f"/api/runs/run-1/events?after_id={first}", headers=headers)
    assert "n\":1" not in response.text
    assert "n\":2" in response.text


def test_delete_run_endpoint(api) -> None:
    client, manager, headers = api
    insert_run(manager.db_path, "run-1", status="done")

    response = client.delete("/api/runs/run-1", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"deleted": "run-1"}
    assert manager.get_run("run-1") is None

    assert client.delete("/api/runs/run-1", headers=headers).status_code == 404


def test_delete_run_refuses_active_runs(api) -> None:
    client, manager, headers = api
    insert_run(manager.db_path, "run-1", status="running")
    assert client.delete("/api/runs/run-1", headers=headers).status_code == 409


def test_delete_expired_endpoint(api) -> None:
    client, manager, headers = api
    insert_run(manager.db_path, "old", status="done", updated_at=_now_iso(40))
    insert_run(manager.db_path, "new", status="done", updated_at=_now_iso(1))

    response = client.delete("/api/runs/expired", headers=headers)
    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    assert manager.get_run("old") is None
    assert manager.get_run("new") is not None


# ---------------------------------------------------------------------------
# Section 3: cancellation
# ---------------------------------------------------------------------------


def test_cancel_endpoint_409_for_completed_run(api) -> None:
    client, manager, headers = api
    insert_run(manager.db_path, "run-1", status="done")
    response = client.post("/api/runs/run-1/cancel", headers=headers)
    assert response.status_code == 409


def test_cancel_endpoint_404_for_missing_run(api) -> None:
    client, _manager, headers = api
    response = client.post("/api/runs/missing/cancel", headers=headers)
    assert response.status_code == 404


def test_cancel_endpoint_200_for_active_run(api) -> None:
    client, manager, headers = api
    insert_run(manager.db_path, "run-1", status="running")
    session = RunSession("run-1", workspace=".", executing=False)
    manager.sessions["run-1"] = session

    response = client.post("/api/runs/run-1/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] in ("cancelling", "cancelled")
    assert manager.get_run("run-1").status in ("cancelled", "cancelling")


# ---------------------------------------------------------------------------
# Section 4: retention
# ---------------------------------------------------------------------------

def test_events_beyond_max_are_pruned(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    insert_run(db, "run-1", status="done")
    manager = make_manager(tmp_path)
    session = RunSession("run-1", max_events=5)

    for index in range(12):
        manager.publish(session, "custom", {"i": index})

    events = manager.get_run_events("run-1")
    assert len(events) == 5
    assert events[-1].payload["i"] == 11
    assert len(session.events) == 5


def test_expired_runs_are_cleaned(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SYMBIOT_RUN_RETENTION_DAYS", "30")
    db = tmp_path / "runs.db"
    manager = make_manager(tmp_path)
    insert_run(db, "old", status="done", updated_at=_now_iso(40))
    insert_run(db, "recent", status="done", updated_at=_now_iso(1))

    assert manager.cleanup_expired_runs() == 1
    assert manager.get_run("old") is None
    assert manager.get_run("recent") is not None


def test_active_runs_never_cleaned(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    manager = make_manager(tmp_path)
    insert_run(db, "old-running", status="running", updated_at=_now_iso(60))
    insert_run(db, "old-interrupted", status="interrupted", updated_at=_now_iso(60))

    assert manager.cleanup_expired_runs() == 0
    assert manager.get_run("old-running") is not None
    assert manager.get_run("old-interrupted") is not None


def test_expired_runs_purge_removes_their_events(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    manager = make_manager(tmp_path)
    insert_run(db, "old", status="done", updated_at=_now_iso(40))
    manager.publish(RunSession("old"), "custom", {"n": 1})

    manager.cleanup_expired_runs()
    assert manager.get_run("old") is None
    assert manager.get_run_events("old") == []
