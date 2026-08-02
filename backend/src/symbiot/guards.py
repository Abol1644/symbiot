from datetime import datetime, timezone

from symbiot.schemas import Budget
from symbiot.state import LoopState


class BudgetExhaustedError(Exception):
    pass


class RunTimeoutError(Exception):
    pass


def check_budget(state: LoopState) -> None:
    budget = state["budget"]
    if budget.tokens_used >= budget.token_cap:
        raise BudgetExhaustedError(f"Token cap reached: {budget.tokens_used}/{budget.token_cap}")
    if budget.llm_calls >= budget.llm_call_cap:
        raise BudgetExhaustedError(f"LLM call cap reached: {budget.llm_calls}/{budget.llm_call_cap}")


def update_budget(state: LoopState, tokens_used: int) -> dict:
    budget = state["budget"]
    return {"budget": Budget(
        tokens_used=budget.tokens_used + tokens_used,
        token_cap=budget.token_cap,
        llm_calls=budget.llm_calls + 1,
        llm_call_cap=budget.llm_call_cap,
    )}


def check_run_timeout(state: LoopState, max_minutes: int = 30) -> None:
    started = state.get("run_started_at")
    if not started:
        return
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()
    if elapsed > max_minutes * 60:
        raise RunTimeoutError(f"Run timeout: {elapsed:.0f}s > {max_minutes}m")
