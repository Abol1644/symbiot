import re
from typing import Any

from symbiot.schemas import Budget, Milestone
from symbiot.state import LoopState

_REQUIRED_SECTIONS = ["## META", "## OBJECTIVE", "## END_CRITERIA", "## MILESTONES", "## BUDGET", "## OUT_OF_SCOPE"]


def _parse_milestone_block(block: str) -> list[Milestone]:
    results: list[Milestone] = []
    pattern = re.compile(r"\{[^}]+\}")
    for match in pattern.finditer(block):
        raw = match.group()
        fields: dict[str, Any] = {}
        id_m = re.search(r"id:\s*(\S+)", raw)
        if id_m:
            fields["id"] = id_m.group(1).rstrip(",")
        title_m = re.search(r"title:\s*(.+?)(?:,\s*(?:acceptance_criteria|max_attempts|id|\}))", raw)
        if title_m:
            fields["title"] = title_m.group(1).strip().rstrip(",")
        ac_m = re.search(r"acceptance_criteria:\s*\[(.*?)\]", raw)
        if ac_m:
            items_raw = ac_m.group(1)
            items = [s.strip().strip("\"'") for s in re.split(r",\s*(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", items_raw) if s.strip()]
            fields["acceptance_criteria"] = items
        ma_m = re.search(r"max_attempts:\s*(\d+)", raw)
        if ma_m:
            fields["max_attempts"] = int(ma_m.group(1))
        if fields.get("id") and fields.get("title"):
            results.append(Milestone(**fields))
    return results


def _parse_budget(section: str) -> Budget:
    tc = re.search(r"token_cap:\s*(\d+)", section)
    tu = re.search(r"tokens_used:\s*(\d+)", section)
    llm_cap = re.search(r"llm_call_cap:\s*(\d+)", section)
    llm_used = re.search(r"llm_calls_used:\s*(\d+)", section)
    return Budget(
        tokens_used=int(tu.group(1)) if tu else 0,
        token_cap=int(tc.group(1)) if tc else 2_000_000,
        llm_calls=int(llm_used.group(1)) if llm_used else 0,
        llm_call_cap=int(llm_cap.group(1)) if llm_cap else 100,
    )


def _parse_spec(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    meta_match = re.search(r"## META\s*\n(.+)", raw)
    meta_line = meta_match.group(1).strip() if meta_match else ""
    for part in re.split(r"\s*\|\s*", meta_line):
        for key in ["name", "stack", "runtime", "entrypoint", "smoke_command"]:
            m = re.match(rf"{key}:\s*(.+)", part)
            if m:
                result[key] = m.group(1).strip()
    objective_match = re.search(r"## OBJECTIVE\s*\n(.+?)(?=\n##|\Z)", raw, re.DOTALL)
    if objective_match:
        result["objective"] = objective_match.group(1).strip()
    return result


def validator(state: LoopState) -> dict:
    raw = state["raw_spec"]
    for section in _REQUIRED_SECTIONS:
        if section not in raw:
            return {"status": "rejected"}

    spec = _parse_spec(raw)
    milestones = _parse_milestone_block(raw)
    budget = _parse_budget(raw)
    return {"spec": spec, "milestones": milestones, "budget": budget, "status": "running"}
