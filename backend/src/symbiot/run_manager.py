"""Checkpointed graph runs, SQLite persistence, and an SSE event broker.

Runs and events are persisted to ``SYMBIOT_DATA_DIR/runs.db`` (default
``~/.symbiot/runs.db``) through a single background asyncio loop using
aiosqlite.  Live sessions keep an in-memory event tail so SSE streaming for
running runs stays fast; every event is also inserted into SQLite, which makes
history replayable after a restart.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, time as datetime_time, UTC
from pathlib import Path
from typing import Any
from collections.abc import Iterator, Mapping

import aiosqlite
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from symbiot.graph import builder

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path.home() / ".symbiot"

_ACTIVE_STATUSES = {"pending", "running", "cancelling", "interrupted"}
_COMPLETED_STATUSES = {"done", "failed", "cancelled", "rejected"}


class RunCancelled(RuntimeError):
    """Raised when a run is cancelled between graph nodes."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump())
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return _json_safe(value.value)
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _project_name(raw_spec: str) -> str:
    match = re.search(r"(?im)^name:\s*([^|\n]+)", raw_spec)
    return match.group(1).strip() if match else "untitled mission"


def _spec_hash(raw_spec: str) -> str:
    return hashlib.sha256(raw_spec.encode("utf-8")).hexdigest()


def _sse_frame(event_type: str, payload: Any) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


@dataclass
class RunSession:
    run_id: str
    events: list[tuple[int, str, Any]] = field(default_factory=list)
    status: str = "queued"
    waiting_for_human: bool = False
    closed: bool = False
    lock: threading.Condition = field(default_factory=threading.Condition)
    workspace: str = ""
    executing: bool = False
    max_events: int = 10000
    last_event_id: int = 0

    def publish(self, event: str, data: Any) -> None:
        with self.lock:
            self.events.append((0, event, _json_safe(data)))
            self.lock.notify_all()

    def close(self, status: str) -> None:
        with self.lock:
            self.status = status
            self.closed = True
            self.lock.notify_all()


@dataclass
class RunSummary:
    run_id: str
    project_name: str
    status: str
    created_at: str
    updated_at: str
    spec_hash: str | None = None
    event_count: int = 0


@dataclass
class RunEvent:
    id: int
    run_id: str
    event_type: str
    payload: Any
    created_at: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    spec_hash TEXT,
    checkpoint_thread_id TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
"""


class RunManager:
    def __init__(
        self,
        checkpoint_path: str | Path | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        default_checkpoint = Path(__file__).resolve().parents[3] / "backend" / "checkpoints.db"
        self.checkpoint_path = Path(
            checkpoint_path or os.getenv("SYMBIOT_CHECKPOINT_DB", default_checkpoint)
        )
        data_dir = Path(os.getenv("SYMBIOT_DATA_DIR", _DEFAULT_DATA_DIR))
        self.db_path = Path(db_path or os.getenv("SYMBIOT_RUNS_DB", data_dir / "runs.db"))
        self.sessions: dict[str, RunSession] = {}
        self.lock = threading.Lock()
        self._db_loop: asyncio.AbstractEventLoop | None = None

        self._start_db_loop()
        self._recover_interrupted()
        self.cleanup_expired_runs()
        self._start_cleanup_loop()

    # ------------------------------------------------------------------ db

    def _start_db_loop(self) -> None:
        loop = asyncio.new_event_loop()
        started = threading.Event()

        def _run_loop() -> None:
            asyncio.set_event_loop(loop)
            started.set()
            loop.run_forever()

        threading.Thread(target=_run_loop, daemon=True, name="symbiot-db").start()
        started.wait()
        self._db_loop = loop
        self._run(self._init_db())

    def _run(self, coro, timeout: float = 30.0) -> Any:
        if self._db_loop is None:
            raise RuntimeError("database loop is not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._db_loop)
        return future.result(timeout=timeout)

    async def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    def _conn(self) -> aiosqlite.Connection:
        return aiosqlite.connect(str(self.db_path))

    # ------------------------------------------------------------ runs CRUD

    def start(self, input_state: Mapping[str, Any]) -> RunSession:
        run_id = str(uuid.uuid4())
        raw_spec = str(input_state.get("raw_spec") or "")
        project_name = _project_name(raw_spec)
        spec_hash = _spec_hash(raw_spec)
        created_at = _now()
        self._run(
            self._insert_run(run_id, project_name, "running", created_at, spec_hash)
        )
        max_events = max(1, int(os.getenv("SYMBIOT_MAX_EVENTS_PER_RUN", "10000")))
        session = RunSession(run_id=run_id, status="running", max_events=max_events)
        with self.lock:
            self.sessions[run_id] = session
        self.publish(session, "metadata", {"run_id": run_id})
        thread = threading.Thread(
            target=self._execute,
            args=(session, dict(input_state), None),
            daemon=True,
            name=f"symbiot-run-{run_id[:8]}",
        )
        thread.start()
        return session

    def resume(self, run_id: str, decision: Any) -> int:
        session = self.get(run_id)
        if session is None:
            raise KeyError("run not found")
        with session.lock:
            if not session.waiting_for_human:
                raise ValueError("run is not waiting for a human decision")
            cursor = session.last_event_id
            session.waiting_for_human = False
            session.closed = False
            session.status = "running"
        self.update_run_status(run_id, "running")
        thread = threading.Thread(
            target=self._execute,
            args=(session, None, decision),
            daemon=True,
            name=f"symbiot-resume-{run_id[:8]}",
        )
        thread.start()
        return cursor

    def get(self, run_id: str) -> RunSession | None:
        with self.lock:
            return self.sessions.get(run_id)

    def get_run(self, run_id: str) -> RunSummary | None:
        rows = self._run(self._query_run(run_id))
        return rows[0] if rows else None

    def get_run_history(self, limit: int = 50) -> list[RunSummary]:
        return self._run(self._query_runs(max(1, limit)))

    def get_run_events(self, run_id: str, after_id: int | None = None) -> list[RunEvent]:
        return self._run(self._query_events(run_id, after_id))

    def update_run_status(self, run_id: str, status: str) -> None:
        self._run(self._update_status(run_id, status))

    def delete_run(self, run_id: str) -> None:
        summary = self.get_run(run_id)
        if summary is None:
            raise KeyError("run not found")
        if summary.status in _ACTIVE_STATUSES:
            raise ValueError(f"run is still active: {summary.status}")
        self._run(self._delete_run(run_id))
        with self.lock:
            self.sessions.pop(run_id, None)

    # ---------------------------------------------------------- cancellation

    def cancel_run(self, run_id: str) -> str:
        summary = self.get_run(run_id)
        if summary is None:
            raise KeyError("run not found")
        if summary.status in _COMPLETED_STATUSES:
            raise ValueError(f"run already completed: {summary.status}")
        self.update_run_status(run_id, "cancelling")
        session = self.get(run_id)
        if session is None or not session.executing:
            self._cleanup_sandbox(session)
            self.update_run_status(run_id, "cancelled")
            if session is not None:
                with session.lock:
                    session.status = "cancelled"
                    session.closed = True
                    session.lock.notify_all()
            return "cancelled"
        return "cancelling"

    def check_cancelled(self, run_id: str) -> bool:
        try:
            summary = self.get_run(run_id)
        except Exception:
            return False
        return summary is not None and summary.status == "cancelling"

    def _raise_if_cancelled(self, run_id: str) -> None:
        if self.check_cancelled(run_id):
            raise RunCancelled(run_id)

    def _cleanup_sandbox(self, session: RunSession | None) -> None:
        pass

    # -------------------------------------------------------------- events

    def publish(self, session: RunSession, event: str, data: Any) -> int:
        payload = _json_safe(data)
        created_at = _now()
        event_id = self._run(
            self._insert_event(session.run_id, event, payload, created_at)
        )
        with session.lock:
            session.events.append((event_id, event, payload))
            session.last_event_id = event_id
            overflow = len(session.events) - session.max_events
            if overflow > 0:
                del session.events[:overflow]
                logger.warning(
                    "pruned %d events for run %s (max %d)",
                    overflow,
                    session.run_id,
                    session.max_events,
                )
                self._run(self._prune_events(session.run_id, session.max_events))
            session.lock.notify_all()
        return event_id

    def events(self, run_id: str, after_id: int = 0) -> Iterator[str]:
        session = self.get(run_id)
        if session is None:
            for event in self.get_run_events(run_id, after_id=after_id):
                yield _sse_frame(event.event_type, event.payload)
            return
        idx = 0
        while idx < len(session.events) and 0 < session.events[idx][0] <= after_id:
            idx += 1
        while True:
            with session.lock:
                while idx >= len(session.events) and not session.closed:
                    session.lock.wait(timeout=15.0)
                if idx < len(session.events):
                    _event_id, event_type, payload = session.events[idx]
                    idx += 1
                    yield _sse_frame(event_type, payload)
                    continue
                if session.closed:
                    return
                yield ": keep-alive\n\n"

    # ------------------------------------------------------------ retention

    def cleanup_expired_runs(self) -> int:
        days = max(0, int(os.getenv("SYMBIOT_RUN_RETENTION_DAYS", "30")))
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        return self._run(self._delete_expired(cutoff))

    def _start_cleanup_loop(self) -> None:
        interval = max(60, int(os.getenv("SYMBIOT_CLEANUP_INTERVAL_SECONDS", "3600")))

        def loop() -> None:
            while True:
                time.sleep(interval)
                try:
                    self.cleanup_expired_runs()
                except Exception as exc:
                    logger.warning("run retention cleanup failed: %s", exc)

        threading.Thread(target=loop, daemon=True, name="symbiot-retention").start()

    def _recover_interrupted(self) -> None:
        now = _now()
        self._run(
            self._recover_runs(now, tuple(sorted(_ACTIVE_STATUSES - {"interrupted"})))
        )

    # -------------------------------------------------------- sql statements

    async def _insert_run(
        self,
        run_id: str,
        project_name: str,
        status: str,
        created_at: str,
        spec_hash: str,
    ) -> None:
        async with self._conn() as db:
            await db.execute(
                "INSERT INTO runs (run_id, project_name, status, created_at, updated_at, spec_hash, checkpoint_thread_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, project_name, status, created_at, created_at, spec_hash, run_id),
            )
            await db.commit()

    async def _insert_event(
        self, run_id: str, event_type: str, payload: Any, created_at: str
    ) -> int:
        async with self._conn() as db:
            cursor = await db.execute(
                "INSERT INTO events (run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                (run_id, event_type, json.dumps(payload, separators=(",", ":")), created_at),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def _prune_events(self, run_id: str, max_events: int) -> None:
        async with self._conn() as db:
            await db.execute(
                "DELETE FROM events WHERE run_id = ? AND id NOT IN "
                "(SELECT id FROM events WHERE run_id = ? ORDER BY id DESC LIMIT ?)",
                (run_id, run_id, max_events),
            )
            await db.commit()

    async def _update_status(self, run_id: str, status: str) -> None:
        async with self._conn() as db:
            await db.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, _now(), run_id),
            )
            await db.commit()

    async def _query_run(self, run_id: str) -> list[RunSummary]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT run_id, project_name, status, created_at, updated_at, spec_hash, "
                "(SELECT COUNT(*) FROM events e WHERE e.run_id = runs.run_id) AS event_count "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            )
            rows = await cursor.fetchall()
        return [RunSummary(**dict(row)) for row in rows]

    async def _query_runs(self, limit: int) -> list[RunSummary]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT run_id, project_name, status, created_at, updated_at, spec_hash, "
                "(SELECT COUNT(*) FROM events e WHERE e.run_id = runs.run_id) AS event_count "
                "FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        return [RunSummary(**dict(row)) for row in rows]

    async def _query_events(
        self, run_id: str, after_id: int | None
    ) -> list[RunEvent]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            if after_id is None:
                cursor = await db.execute(
                    "SELECT id, run_id, event_type, payload, created_at FROM events "
                    "WHERE run_id = ? ORDER BY id",
                    (run_id,),
                )
            else:
                cursor = await db.execute(
                    "SELECT id, run_id, event_type, payload, created_at FROM events "
                    "WHERE run_id = ? AND id > ? ORDER BY id",
                    (run_id, after_id),
                )
            rows = await cursor.fetchall()
        events = []
        for row in rows:
            data = dict(row)
            try:
                data["payload"] = json.loads(data["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                data["payload"] = data["payload"]
            events.append(RunEvent(**data))
        return events

    async def _delete_run(self, run_id: str) -> None:
        async with self._conn() as db:
            await db.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
            await db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            await db.commit()

    async def _delete_expired(self, cutoff: str) -> int:
        async with self._conn() as db:
            placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
            cursor = await db.execute(
                "DELETE FROM runs WHERE updated_at < ? AND status NOT IN ("
                + placeholders
                + ")",
                (cutoff, *_ACTIVE_STATUSES),
            )
            deleted = cursor.rowcount
            await db.execute(
                "DELETE FROM events WHERE run_id NOT IN (SELECT run_id FROM runs)"
            )
            await db.commit()
            return int(deleted)

    async def _recover_runs(self, now: str, statuses: tuple[str, ...]) -> None:
        placeholders = ",".join("?" for _ in statuses)
        async with self._conn() as db:
            await db.execute(
                "UPDATE runs SET status = 'interrupted', updated_at = ? "
                "WHERE status IN (" + placeholders + ")",
                (now, *statuses),
            )
            await db.commit()

    # ------------------------------------------------------------- execution

    def _execute(
        self,
        session: RunSession,
        input_state: Mapping[str, Any] | None,
        decision: Any | None,
    ) -> None:
        session.executing = True
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.checkpoint_path), check_same_thread=False)
        try:
            checkpointed_graph = builder.compile(checkpointer=SqliteSaver(connection))
            config = {"configurable": {"thread_id": session.run_id}}
            graph_input: Any = Command(resume=decision) if decision is not None else input_state
            self._raise_if_cancelled(session.run_id)
            for item in checkpointed_graph.stream(
                graph_input,
                config=config,
                stream_mode=["updates", "custom"],
            ):
                self._raise_if_cancelled(session.run_id)
                if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
                    mode, payload = item
                else:
                    mode, payload = "updates", item
                safe_payload = _json_safe(payload)
                if isinstance(safe_payload, dict):
                    if safe_payload.get("workspace"):
                        session.workspace = str(safe_payload["workspace"])
                    for value in safe_payload.values():
                        if isinstance(value, dict) and value.get("workspace"):
                            session.workspace = str(value["workspace"])
                self.publish(session, mode, safe_payload)
                if mode == "updates" and isinstance(safe_payload, dict) and "__interrupt__" in safe_payload:
                    with session.lock:
                        session.status = "interrupted"
                        session.waiting_for_human = True
                        session.closed = True
                        session.lock.notify_all()
                    self.update_run_status(session.run_id, "interrupted")
                    return
            self._raise_if_cancelled(session.run_id)
            session.close("done")
            self.update_run_status(session.run_id, "done")
        except RunCancelled:
            self._cleanup_sandbox(session)
            self.publish(session, "status", {"status": "cancelled"})
            session.close("cancelled")
            self.update_run_status(session.run_id, "cancelled")
        except Exception:
            self.publish(session, "error", {"message": "run failed; inspect the run history for details"})
            session.close("error")
            self.update_run_status(session.run_id, "failed")
        finally:
            connection.close()
            session.executing = False
