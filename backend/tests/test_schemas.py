from symbiot.nodes.validator import validator
from symbiot import schemas
from symbiot.schemas import Budget, Milestone
from symbiot.providers import redact_sensitive_text
from symbiot import graph as graph_module


def test_validator_persists_run_provider_selection_without_secrets() -> None:
    result = validator(
        {
            "raw_spec": """## META
name: demo | stack: python 3.12 | runtime: cli

## OBJECTIVE
demo

## END_CRITERIA
- works

## MILESTONES
- {id: m1, title: demo, acceptance_criteria: [\"works\"], max_attempts: 2}

## BUDGET
token_cap: 1000
llm_call_cap: 4
cost_cap_usd: 0.50

## OUT_OF_SCOPE
none
""",
            "run_config": {
                "primary": {"provider": "anthropic", "model": "claude-test"},
                "fallbacks": [{"provider": "openrouter", "model": "router-test"}],
            },
        }
    )
    assert result["status"] == "running"
    assert result["run_config"]["primary"] == {
        "provider": "anthropic",
        "model": "claude-test",
    }
    assert result["run_config"]["fallbacks"][0]["provider"] == "openrouter"
    assert result["budget"].cost_cap_usd == 0.5
    assert "api_key" not in result["run_config"]


def test_budget_defaults_include_provider_usage_maps() -> None:
    budget = Budget()
    assert budget.tokens_by_provider == {}
    assert budget.cost_by_provider == {}
    assert budget.calls_by_provider == {}


def test_escalation_payload_contains_redacted_evidence(monkeypatch, tmp_path) -> None:
    captured: dict = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return "abort"

    monkeypatch.setattr(graph_module, "interrupt", fake_interrupt)
    result = graph_module.escalation(
        {
            "milestones": [Milestone(id="m1", title="proof", acceptance_criteria=["works"])],
            "current": 0,
            "attempts": 3,
            "test_report": schemas.TestReport(passed=False, failures=["assert failed"], confidence=0.1, artifacts=[]),
            "test_output": "API_KEY=sk-test-key\nassert failed",
            "workspace": str(tmp_path),
        }
    )
    payload = captured["payload"]
    assert payload["kind"] == "escalation"
    assert payload["options"] == ["retry", "edit", "abort"]
    assert "sk-test-key" not in payload["test_output"]
    assert result["status_reason"] == "human_abort"


def test_sensitive_event_redaction_handles_assignments() -> None:
    assert "sk-test-key" not in redact_sensitive_text("API_KEY=sk-test-key")
