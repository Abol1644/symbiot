from typing import TypedDict
from .schemas import Milestone, Plan, TestReport, Budget

class LoopState(TypedDict, total=False):
    raw_spec: str
    spec: dict
    milestones: list[Milestone]
    current: int
    plan: Plan | None
    workspace: str
    test_report: TestReport | None
    attempts: int
    lessons: list[str]
    budget: Budget
    container_id: str
    status: str                # running | passed | failed | rejected
    status_reason: str
    deploy_result: dict
    deploy_approved: bool
    run_started_at: str
    tokens_by_agent: dict[str, int]
    run_config: dict
    human_guidance: str
    test_output: str
    file_tree: list[dict]
    source_path: str
