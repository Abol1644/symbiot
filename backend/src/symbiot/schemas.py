from typing import Literal
from pydantic import BaseModel, Field


class ModelSelection(BaseModel):
    provider: str
    model: str


class RunConfig(BaseModel):
    primary: ModelSelection = Field(
        default_factory=lambda: ModelSelection(provider="openai", model="gpt-4o-mini")
    )
    fallbacks: list[ModelSelection] = Field(default_factory=list)
    timeout_minutes: int = Field(default=30, ge=1, le=30)

class Milestone(BaseModel):
    id: str
    title: str
    acceptance_criteria: list[str]
    max_attempts: int = 3

class PlanStep(BaseModel):
    action: Literal["create_file", "edit_file", "run_command", "delete_file"]
    target: str
    detail: str
    content: str | None = None


class FileContent(BaseModel):
    content: str

class Plan(BaseModel):
    type: Literal["build", "debug", "refactor"]
    milestone_id: str
    steps: list[PlanStep]

class TestReport(BaseModel):
    passed: bool
    failures: list[str]
    confidence: float          # 0..1, below 0.7 routes to planner even on pass
    artifacts: list[str]       # paths to executed test output — proof, not vibes

class Budget(BaseModel):
    tokens_used: int = 0
    token_cap: int = 2_000_000
    llm_calls: int = 0
    llm_call_cap: int = 100
    cost_usd: float = 0.0
    cost_cap_usd: float | None = None
    tokens_by_provider: dict[str, int] = Field(default_factory=dict)
    cost_by_provider: dict[str, float] = Field(default_factory=dict)
    calls_by_provider: dict[str, int] = Field(default_factory=dict)


class DeployResult(BaseModel):
    image: str
    tag: str
    smoke_test_passed: bool
    smoke_test_output: str
