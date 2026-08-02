from pydantic import BaseModel

from symbiot.run_manager import RunSession, _json_safe


class Payload(BaseModel):
    value: str


def test_json_safe_serializes_checkpoint_values_without_secrets() -> None:
    assert _json_safe(Payload(value="ok")) == {"value": "ok"}
    assert _json_safe({"items": (1, 2)}) == {"items": [1, 2]}


def test_run_session_sse_cursor_and_close() -> None:
    session = RunSession("run-1")
    session.publish("metadata", {"run_id": "run-1"})
    session.close("done")
    events = list(session_events(session))
    assert events[0].startswith("event: metadata\n")
    assert '"run_id":"run-1"' in events[0]


def session_events(session: RunSession):
    from symbiot.run_manager import RunManager

    manager = RunManager()
    manager.sessions[session.run_id] = session
    return manager.events(session.run_id)
