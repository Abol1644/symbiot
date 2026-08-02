from pathlib import Path

from langgraph.config import get_stream_writer

from symbiot.llm import invoke_structured
from symbiot.schemas import Plan
from symbiot.state import LoopState
from symbiot.guards import BudgetLedger, BudgetExhaustedError, RunTimeoutError, check_budget, check_run_timeout


def _load_prompt(filename: str) -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / filename
    return path.read_text()


def planner(state: LoopState) -> dict:
    writer = get_stream_writer()
    try:
        check_budget(state)
    except BudgetExhaustedError as e:
        return {"status": "failed", "status_reason": str(e)}
    try:
        check_run_timeout(state)
    except RunTimeoutError as e:
        return {"status": "failed", "status_reason": str(e)}

    ledger = BudgetLedger(state)

    spec = state["spec"]
    milestone = state["milestones"][state["current"]]
    attempts = state["attempts"]
    lessons = state["lessons"]
    test_report = state.get("test_report")

    plan_type = "build"
    if attempts > 0:
        if test_report and not test_report.passed:
            plan_type = "debug"
        elif test_report and test_report.passed and test_report.confidence < 0.7:
            plan_type = "refactor"
        else:
            plan_type = "debug"

    writer({"agent": "planner", "msg": f"Analyzing milestone {milestone.id}"})

    user_parts = [
        f"## Plan Type: {plan_type}\n\n## Project Specification\nname: {spec.get('name', 'unknown')}\nstack: {spec.get('stack', 'python')}\nruntime: {spec.get('runtime', 'cli')}\nobjective: {spec.get('objective', '')}\n",
        f"## Current Milestone\nid: {milestone.id}\ntitle: {milestone.title}\nacceptance criteria:\n" + "\n".join(f"- {c}" for c in milestone.acceptance_criteria),
    ]

    ft = state.get("file_tree", [])
    if ft:
        lines = "\n".join(f"- {f['path']} ({f['status']})" for f in ft[:60])
        user_parts.append(f"## Existing Files in Workspace\n{lines}")

    if lessons:
        user_parts.append("## Lessons Learned\n" + "\n".join(f"- {l}" for l in lessons))
    if test_report:
        user_parts.append(f"## Test Report\npassed: {test_report.passed}\nconfidence: {test_report.confidence}\nfailures: {test_report.failures}")
    if state.get("human_guidance"):
        user_parts.append(f"## Human Guidance\n{state['human_guidance']}")

    user_prompt = "\n\n".join(user_parts)

    writer({"agent": "planner", "msg": f"Drafting {plan_type} plan"})

    try:
        plan, tokens = invoke_structured(
            system_prompt=_load_prompt("planner.md"),
            user_prompt=user_prompt,
            schema=Plan,
            run_config=state.get("run_config"),
            ledger=ledger,
            agent="planner",
        )
    except BudgetExhaustedError as e:
        return {"status": "failed", "status_reason": str(e), **ledger.state_update()}
    except Exception:
        return {
            "status": "failed",
            "status_reason": "planner LLM invocation failed",
            **ledger.state_update(),
        }

    return {"plan": plan, "status": "running", **ledger.state_update()}
