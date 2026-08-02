from pathlib import Path

from symbiot.llm import invoke_structured
from symbiot.schemas import Plan
from symbiot.state import LoopState
from symbiot.guards import check_budget, update_budget, BudgetExhaustedError, check_run_timeout, RunTimeoutError


def _load_prompt(filename: str) -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / filename
    return path.read_text()


def planner(state: LoopState) -> dict:
    try:
        check_budget(state)
    except BudgetExhaustedError as e:
        return {"status": "failed", "status_reason": str(e)}
    try:
        check_run_timeout(state)
    except RunTimeoutError as e:
        return {"status": "failed", "status_reason": str(e)}

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

    user_parts = [
        f"## Plan Type: {plan_type}\n\n## Project Specification\nname: {spec.get('name', 'unknown')}\nstack: {spec.get('stack', 'python')}\nruntime: {spec.get('runtime', 'cli')}\nobjective: {spec.get('objective', '')}\n",
        f"## Current Milestone\nid: {milestone.id}\ntitle: {milestone.title}\nacceptance criteria:\n" + "\n".join(f"- {c}" for c in milestone.acceptance_criteria),
    ]
    if lessons:
        user_parts.append("## Lessons Learned\n" + "\n".join(f"- {l}" for l in lessons))
    if test_report:
        user_parts.append(f"## Test Report\npassed: {test_report.passed}\nconfidence: {test_report.confidence}\nfailures: {test_report.failures}")

    user_prompt = "\n\n".join(user_parts)

    try:
        plan, tokens = invoke_structured(
            system_prompt=_load_prompt("planner.md"),
            user_prompt=user_prompt,
            schema=Plan,
        )
    except Exception:
        return {"status": "failed", "status_reason": "planner LLM invocation failed"}

    budget_update = update_budget(state, tokens)
    return {"plan": plan, "status": "running", **budget_update}
