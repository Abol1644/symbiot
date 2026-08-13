r"""End-to-end smoke test against a real OpenAI-compatible provider.

Gate: ``SYMBIOT_REAL_PROVIDER_TEST=1`` **and** ``SYMBIOT_TEST_API_KEY`` set
to an API key for the current ``openai``-shaped model.

Run manually (never in CI):

    SYMBIOT_REAL_PROVIDER_TEST=1 SYMBIOT_TEST_API_KEY=sk-... \
      uv run pytest backend/tests/test_real_provider.py -v -s

Budget is clamped at 5 LLM calls / 10 k tokens and the graph timeout is
2 minutes, so a single run costs at most a few cents.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

pytestmark = [
    pytest.mark.real_provider,
    pytest.mark.skipif(
        os.getenv("SYMBIOT_REAL_PROVIDER_TEST") != "1",
        reason="set SYMBIOT_REAL_PROVIDER_TEST=1 and SYMBIOT_TEST_API_KEY to run",
    ),
]

ADDER_SPEC = """## META
name: real-adder | stack: python 3.12 | runtime: cli

## OBJECTIVE
A Python module that adds two numbers together.

## END_CRITERIA
- adder.add(2, 3) == 5
- pytest suite passes

## MILESTONES
- {id: m1, title: implement add, acceptance_criteria: ["adder.add(2,3)==5","pytest passes"], max_attempts: 1}

## BUDGET
token_cap: 10000
llm_call_cap: 5

## OUT_OF_SCOPE
no database, no web UI
"""


def _cleanup_workspace(path: str | None) -> None:
    if not path:
        return
    try:
        shutil.rmtree(path)
    except Exception:
        pass


def test_real_provider_end_to_end() -> None:
    api_key = os.getenv("SYMBIOT_TEST_API_KEY")
    if not api_key:
        pytest.skip("SYMBIOT_TEST_API_KEY is not set")

    os.environ["OPENAI_API_KEY"] = api_key

    from symbiot.graph import graph

    run_config = {
        "primary": {"provider": "openai", "model": "gpt-4o-mini"},
        "fallbacks": [],
        "timeout_minutes": 2,
    }

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    compiled = graph.compile(checkpointer=SqliteSaver(conn))
    config = {"configurable": {"thread_id": "test-real-provider"}}

    input_state = {"raw_spec": ADDER_SPEC, "run_config": run_config}
    final_state: dict = {}
    exception: BaseException | None = None

    def run() -> None:
        nonlocal final_state, exception
        try:
            for item in compiled.stream(
                input_state, config=config, stream_mode=["updates", "custom"]
            ):
                mode, payload = item
                if (
                    mode == "updates"
                    and isinstance(payload, dict)
                    and "__interrupt__" in payload
                ):
                    break

            for item in compiled.stream(
                Command(resume="skip"),
                config=config,
                stream_mode=["updates", "custom"],
            ):
                mode, payload = item

            snapshot = compiled.get_state(config)
            if snapshot and snapshot.values:
                final_state = dict(snapshot.values)
        except BaseException as exc:
            exception = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=120)
    if t.is_alive():
        _cleanup_workspace(final_state.get("workspace"))
        raise TimeoutError("run did not complete within 120 s")

    try:
        if exception is not None:
            raise exception

        plan = final_state.get("plan")
        assert plan is not None, "no plan generated"
        assert plan.steps, "plan has no steps"

        ws = final_state.get("workspace", "")
        assert ws, "no workspace directory"
        assert Path(ws).is_dir(), f"workspace does not exist: {ws}"
        files = list(Path(ws).rglob("*.py"))
        assert files, "no Python files were written"

        test_report = final_state.get("test_report")
        assert test_report is not None, "no test report"
        assert test_report.passed, "tests did not pass"

        budget = final_state.get("budget")
        assert budget is not None, "no budget tracked"
        assert budget.tokens_used > 0, "no tokens consumed"

        assert budget.tokens_used <= 10_000, (
            f"token cap exceeded: {budget.tokens_used}"
        )
        assert budget.llm_calls <= 5, f"call cap exceeded: {budget.llm_calls}"
    finally:
        _cleanup_workspace(final_state.get("workspace"))
