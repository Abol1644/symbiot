from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
import subprocess

from symbiot.state import LoopState
from symbiot.providers import redact_sensitive_text
from symbiot.nodes.validator import validator
from symbiot.nodes.base import base
from symbiot.nodes.planner import planner
from symbiot.nodes.programmer import programmer
from symbiot.nodes.tester import tester
from symbiot.nodes.deployer import deployer
from symbiot.nodes.router import route_after_test, route_after_advance


def advance(state: LoopState) -> dict:
    from symbiot.sandbox.git_ops import commit_all
    milestone = state["milestones"][state["current"]]
    conf = state["test_report"].confidence
    commit_all(state["workspace"], f"milestone {milestone.id} passed (confidence {conf:.2f})")
    lesson = f"Milestone {milestone.id}: passed (confidence {conf:.2f})"
    return {
        "current": state["current"] + 1,
        "attempts": 0,
        "lessons": state["lessons"] + [lesson],
    }


def _failure(state: LoopState) -> dict:
    return {"status": "failed"}


def _cleanup(state: LoopState) -> dict:
    from symbiot.sandbox.docker_sandbox import Sandbox
    ws = state.get("workspace")
    if ws:
        sandbox = Sandbox(ws)
        sandbox.stop()
    if state.get("deploy_result") or state.get("deploy_approved") is False:
        return {"status": "passed"}
    return {}


def route_after_node(state: LoopState) -> str:
    if state.get("status") == "failed":
        return "cleanup"
    return "continue"


def escalation(state: LoopState) -> dict:
    milestone = state["milestones"][state["current"]]
    report = state.get("test_report")
    failures = [redact_sensitive_text(str(failure), limit=2000) for failure in report.failures] if report else ["no test report"]

    context_diff = ""
    workspace = state.get("workspace")
    if workspace:
        try:
            diff = subprocess.run(
                ["git", "diff", "--no-color", "HEAD"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=3,
            )
            context_diff = redact_sensitive_text(diff.stdout, limit=12000)
        except (OSError, subprocess.SubprocessError):
            context_diff = "Unable to collect workspace diff."

    decision = interrupt({
        "kind": "escalation",
        "question": f"Milestone '{milestone.title}' failed after {state['attempts']} attempts.",
        "failures": failures,
        "test_output": redact_sensitive_text(str(state.get("test_output", "")), limit=12000),
        "context_diff": context_diff,
        "options": ["retry", "edit", "abort"],
    })

    if isinstance(decision, dict):
        action = str(decision.get("action", "")).lower()
        guidance = str(decision.get("guidance", "")).strip()
    else:
        action = str(decision).lower()
        guidance = ""
    if "retry" in action or "edit" in action:
        result = {"attempts": 0, "status": "running"}
        if guidance:
            result["human_guidance"] = redact_sensitive_text(guidance, limit=4000)
        return result
    return {"status": "failed", "status_reason": "human_abort"}


def deploy_gate(state: LoopState) -> dict:
    decision = interrupt({
        "kind": "deploy",
        "question": f"All milestones passed. Deploy '{state['spec']['name']}' as Docker image?",
        "options": ["deploy", "skip"],
    })
    return {"deploy_approved": "deploy" in decision.lower()}


def _route_after_escalation(state: LoopState) -> str:
    if state.get("status") == "running":
        return "retry"
    return "cleanup"


def _route_after_gate(state: LoopState) -> str:
    if state.get("deploy_approved"):
        return "deployer"
    return "cleanup"


builder = StateGraph(LoopState)
builder.add_node("validator", validator)
builder.add_node("base", base)
builder.add_node("planner", planner)
builder.add_node("programmer", programmer)
builder.add_node("tester", tester)
builder.add_node("advance", advance)
builder.add_node("escalation", escalation)
builder.add_node("deploy_gate", deploy_gate)
builder.add_node("deployer", deployer)
builder.add_node("failure", _failure)
builder.add_node("cleanup", _cleanup)

def _route_after_validator(state: LoopState) -> str:
    if state.get("status") == "rejected":
        return "end"
    return "proceed"

builder.add_edge(START, "validator")
builder.add_conditional_edges(
    "validator",
    _route_after_validator,
    {"proceed": "base", "end": "failure"},
)
builder.add_edge("base", "planner")

builder.add_conditional_edges(
    "planner",
    route_after_node,
    {"continue": "programmer", "cleanup": "cleanup"},
)
builder.add_conditional_edges(
    "programmer",
    route_after_node,
    {"continue": "tester", "cleanup": "cleanup"},
)

builder.add_conditional_edges(
    "tester",
    route_after_test,
    {"advance": "advance", "retry": "planner", "fail": "escalation", "cleanup": "cleanup"},
)

builder.add_conditional_edges(
    "escalation",
    _route_after_escalation,
    {"retry": "planner", "cleanup": "cleanup"},
)

builder.add_conditional_edges(
    "advance",
    route_after_advance,
    {"next": "planner", "done": "deploy_gate"},
)

builder.add_conditional_edges(
    "deploy_gate",
    _route_after_gate,
    {"deployer": "deployer", "cleanup": "cleanup"},
)

builder.add_edge("deployer", "cleanup")
builder.add_edge("failure", "cleanup")
builder.add_edge("cleanup", END)

graph = builder.compile()
