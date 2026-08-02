"""Checkpointed graph runs and a small SSE event broker for the web shell."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as datetime_time
from pathlib import Path
from typing import Any, Iterator, Mapping

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from symbiot.graph import builder


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


@dataclass
class RunSession:
    run_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "queued"
    waiting_for_human: bool = False
    closed: bool = False
    lock: threading.Condition = field(default_factory=threading.Condition)

    def publish(self, event: str, data: Any) -> None:
        with self.lock:
            self.events.append({"event": event, "data": _json_safe(data)})
            self.lock.notify_all()

    def close(self, status: str) -> None:
        with self.lock:
            self.status = status
            self.closed = True
            self.lock.notify_all()

    def next_event(self, cursor: int, timeout: float = 15.0) -> tuple[dict[str, Any] | None, bool, bool]:
        with self.lock:
            if cursor >= len(self.events) and not self.closed:
                self.lock.wait(timeout=timeout)
            if cursor < len(self.events):
                return self.events[cursor], False, False
            return None, self.closed, True


class RunManager:
    def __init__(self, checkpoint_path: str | Path | None = None) -> None:
        default_path = Path(__file__).resolve().parents[3] / "backend" / "checkpoints.db"
        self.checkpoint_path = Path(checkpoint_path or os.getenv("SYMBIOT_CHECKPOINT_DB", default_path))
        self.sessions: dict[str, RunSession] = {}
        self.lock = threading.Lock()

    def start(self, input_state: Mapping[str, Any]) -> RunSession:
        run_id = str(uuid.uuid4())
        session = RunSession(run_id=run_id, status="running")
        session.publish("metadata", {"run_id": run_id})
        with self.lock:
            self.sessions[run_id] = session
        thread = threading.Thread(
            target=self._execute,
            args=(session, dict(input_state), None),
            daemon=True,
            name=f"symbiot-run-{run_id[:8]}",
        )
        thread.start()
        return session

    def get(self, run_id: str) -> RunSession | None:
        with self.lock:
            return self.sessions.get(run_id)

    def resume(self, run_id: str, decision: Any) -> int:
        session = self.get(run_id)
        if session is None:
            raise KeyError("run not found")
        with session.lock:
            if not session.waiting_for_human:
                raise ValueError("run is not waiting for a human decision")
            cursor = len(session.events)
            session.waiting_for_human = False
            session.closed = False
            session.status = "running"
        thread = threading.Thread(
            target=self._execute,
            args=(session, None, decision),
            daemon=True,
            name=f"symbiot-resume-{run_id[:8]}",
        )
        thread.start()
        return cursor

    def events(self, run_id: str, after: int = 0) -> Iterator[str]:
        session = self.get(run_id)
        if session is None:
            raise KeyError("run not found")
        cursor = max(0, after)
        while True:
            event, closed, timed_out = session.next_event(cursor)
            if event is not None:
                cursor += 1
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], separators=(',', ':'))}\n\n"
                continue
            if timed_out and not closed:
                yield ": keep-alive\n\n"
                continue
            return

    def _execute(
        self,
        session: RunSession,
        input_state: Mapping[str, Any] | None,
        decision: Any | None,
    ) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.checkpoint_path), check_same_thread=False)
        try:
            checkpointed_graph = builder.compile(checkpointer=SqliteSaver(connection))
            config = {"configurable": {"thread_id": session.run_id}}
            graph_input: Any = Command(resume=decision) if decision is not None else input_state
            for item in checkpointed_graph.stream(
                graph_input,
                config=config,
                stream_mode=["updates", "custom"],
            ):
                if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
                    mode, payload = item
                else:
                    mode, payload = "updates", item
                safe_payload = _json_safe(payload)
                session.publish(mode, safe_payload)
                if mode == "updates" and isinstance(safe_payload, dict) and "__interrupt__" in safe_payload:
                    with session.lock:
                        session.status = "interrupted"
                        session.waiting_for_human = True
                        session.closed = True
                        session.lock.notify_all()
                    return
            session.close("done")
        except Exception:
            session.publish("error", {"message": "run failed; inspect the run history for details"})
            session.close("error")
        finally:
            connection.close()
