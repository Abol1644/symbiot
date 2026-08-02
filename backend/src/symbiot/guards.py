from datetime import datetime, timezone
from typing import Any

from symbiot.schemas import Budget
from symbiot.state import LoopState
from symbiot.providers import ProviderUsage


class BudgetExhaustedError(Exception):
    pass


class RunTimeoutError(Exception):
    pass


def check_budget(state: LoopState) -> None:
    budget = Budget.model_validate(state["budget"])
    if budget.tokens_used >= budget.token_cap:
        raise BudgetExhaustedError(f"Token cap reached: {budget.tokens_used}/{budget.token_cap}")
    if budget.llm_calls >= budget.llm_call_cap:
        raise BudgetExhaustedError(f"LLM call cap reached: {budget.llm_calls}/{budget.llm_call_cap}")
    if budget.cost_cap_usd is not None and budget.cost_usd >= budget.cost_cap_usd:
        raise BudgetExhaustedError(f"Cost cap reached: {budget.cost_usd:.4f}/{budget.cost_cap_usd:.4f}")


class BudgetLedger:
    """Mutable per-node view that reserves every provider attempt before it runs."""

    def __init__(self, state: LoopState) -> None:
        self.budget = Budget.model_validate(state["budget"])
        self.tokens_by_agent = dict(state.get("tokens_by_agent", {}))
        self._agent_delta: dict[str, int] = {}

    def reserve_call(self, provider: str) -> None:
        if self.budget.tokens_used >= self.budget.token_cap:
            raise BudgetExhaustedError(
                f"Token cap reached: {self.budget.tokens_used}/{self.budget.token_cap}"
            )
        if self.budget.llm_calls >= self.budget.llm_call_cap:
            raise BudgetExhaustedError(
                f"LLM call cap reached: {self.budget.llm_calls}/{self.budget.llm_call_cap}"
            )
        if self.budget.cost_cap_usd is not None and self.budget.cost_usd >= self.budget.cost_cap_usd:
            raise BudgetExhaustedError(
                f"Cost cap reached: {self.budget.cost_usd:.4f}/{self.budget.cost_cap_usd:.4f}"
            )
        calls_by_provider = dict(self.budget.calls_by_provider)
        calls_by_provider[provider] = calls_by_provider.get(provider, 0) + 1
        self.budget = self.budget.model_copy(
            update={
                "llm_calls": self.budget.llm_calls + 1,
                "calls_by_provider": calls_by_provider,
            }
        )

    def record_usage(self, usage: ProviderUsage, agent: str) -> None:
        tokens_by_provider = dict(self.budget.tokens_by_provider)
        cost_by_provider = dict(self.budget.cost_by_provider)
        tokens_by_provider[usage.provider] = (
            tokens_by_provider.get(usage.provider, 0) + usage.total_tokens
        )
        cost_by_provider[usage.provider] = (
            cost_by_provider.get(usage.provider, 0.0) + usage.cost_usd
        )
        self.budget = self.budget.model_copy(
            update={
                "tokens_used": self.budget.tokens_used + usage.total_tokens,
                "cost_usd": self.budget.cost_usd + usage.cost_usd,
                "tokens_by_provider": tokens_by_provider,
                "cost_by_provider": cost_by_provider,
            }
        )
        self.tokens_by_agent[agent] = self.tokens_by_agent.get(agent, 0) + usage.total_tokens
        self._agent_delta[agent] = self._agent_delta.get(agent, 0) + usage.total_tokens
        if self.budget.tokens_used > self.budget.token_cap:
            raise BudgetExhaustedError(
                f"Token cap exceeded: {self.budget.tokens_used}/{self.budget.token_cap}"
            )
        if self.budget.cost_cap_usd is not None and self.budget.cost_usd > self.budget.cost_cap_usd:
            raise BudgetExhaustedError(
                f"Cost cap exceeded: {self.budget.cost_usd:.4f}/{self.budget.cost_cap_usd:.4f}"
            )

    def state_update(self) -> dict[str, Any]:
        return {"budget": self.budget, "tokens_by_agent": dict(self.tokens_by_agent)}


def update_budget(
    state: LoopState,
    tokens_used: int,
    agent: str,
    *,
    provider: str = "unknown",
    cost_usd: float = 0.0,
    llm_calls: int = 1,
) -> dict:
    """Compatibility helper for callers that already have a completed request."""

    budget = Budget.model_validate(state["budget"])
    tokens_by_agent = state.get("tokens_by_agent", {}).copy()
    tokens_by_agent[agent] = tokens_by_agent.get(agent, 0) + tokens_used
    tokens_by_provider = dict(budget.tokens_by_provider)
    cost_by_provider = dict(budget.cost_by_provider)
    calls_by_provider = dict(budget.calls_by_provider)
    tokens_by_provider[provider] = tokens_by_provider.get(provider, 0) + tokens_used
    cost_by_provider[provider] = cost_by_provider.get(provider, 0.0) + cost_usd
    calls_by_provider[provider] = calls_by_provider.get(provider, 0) + llm_calls
    return {
        "budget": budget.model_copy(
            update={
                "tokens_used": budget.tokens_used + tokens_used,
                "llm_calls": budget.llm_calls + llm_calls,
                "cost_usd": budget.cost_usd + cost_usd,
                "tokens_by_provider": tokens_by_provider,
                "cost_by_provider": cost_by_provider,
                "calls_by_provider": calls_by_provider,
            }
        ),
        "tokens_by_agent": tokens_by_agent,
    }


def check_run_timeout(state: LoopState, max_minutes: int = 30) -> None:
    started = state.get("run_started_at")
    if not started:
        return
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()
    configured = state.get("run_config", {}).get("timeout_minutes", max_minutes)
    try:
        effective_minutes = min(max_minutes, max(1, int(configured)))
    except (TypeError, ValueError):
        effective_minutes = max_minutes
    if elapsed > effective_minutes * 60:
        raise RunTimeoutError(f"Run timeout: {elapsed:.0f}s > {effective_minutes}m")
