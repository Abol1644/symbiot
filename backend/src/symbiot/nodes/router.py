from symbiot.state import LoopState


def route_after_test(state: LoopState) -> str:
    if state.get("status") == "failed":
        return "cleanup"

    report = state["test_report"]
    milestone = state["milestones"][state["current"]]

    if report is None:
        if state["attempts"] >= milestone.max_attempts:
            return "fail"
        return "retry"

    if report.passed and report.confidence >= 0.7:
        return "advance"
    if state["attempts"] >= milestone.max_attempts:
        return "fail"
    return "retry"


def route_after_advance(state: LoopState) -> str:
    if state["current"] >= len(state["milestones"]):
        return "done"
    return "next"
