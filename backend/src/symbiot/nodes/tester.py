import subprocess
from pathlib import Path

from langgraph.config import get_stream_writer

from symbiot.llm import invoke_structured
from symbiot.providers import redact_sensitive_text
from symbiot.redaction import redact_secrets
from symbiot.schemas import TestReport
from symbiot.git_ops import file_tree
from symbiot.state import LoopState
from symbiot.guards import BudgetLedger, BudgetExhaustedError, RunTimeoutError, check_budget, check_run_timeout


def _load_prompt(filename: str) -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / filename
    return path.read_text()


def _rglob(root: Path, pattern: str) -> list[Path]:
    return sorted(root.rglob(pattern))


def tester(state: LoopState) -> dict:
    writer = get_stream_writer()
    try:
        check_budget(state)
    except BudgetExhaustedError as e:
        return {"status": "failed", "status_reason": str(e), "test_output": ""}
    try:
        check_run_timeout(state)
    except RunTimeoutError as e:
        return {"status": "failed", "status_reason": str(e), "test_output": ""}

    ledger = BudgetLedger(state)

    workspace = state["workspace"]
    milestone = state["milestones"][state["current"]]
    ws_path = Path(workspace)

    artifacts: list[str] = []
    pytest_output = ""

    has_tests = bool(_rglob(ws_path, "test_*.py")) or (ws_path / "tests").is_dir()
    if has_tests:
        writer({"agent": "tester", "msg": "Running pytest"})
        try:
            result = subprocess.run(
                [subprocess.sys.executable, "-m", "pytest", "-v"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=30,
            )
            pytest_output = redact_sensitive_text(
                result.stdout + "\n" + result.stderr, limit=12000
            )
            artifacts.append("pytest output captured")
        except Exception as e:
            pytest_output = redact_sensitive_text(str(e), limit=12000)
            artifacts.append("pytest execution error")

    py_files: list[str] = [
        str(p.relative_to(ws_path)) for p in _rglob(ws_path, "*.py")
    ]
    all_files: list[str] = [
        str(p.relative_to(ws_path))
        for p in _rglob(ws_path, "*")
        if p.is_file()
    ]

    syntax_errors: list[str] = []
    for f in py_files:
        try:
            result = subprocess.run(
                [subprocess.sys.executable, "-m", "py_compile", str(ws_path / f)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                syntax_errors.append(f"{f}: {result.stderr.strip()[:200]}")
        except Exception:
            pass
    if syntax_errors:
        artifacts.append("syntax errors: " + "; ".join(syntax_errors))

    key_contents: list[str] = []
    for f in py_files[:10]:
        fp = ws_path / f
        try:
            key_contents.append(
                f"### {f}\n```\n{redact_secrets(fp.read_text())[:3000]}\n```"
            )
        except Exception:
            pass

    criteria_text = "\n".join(f"- {c}" for c in milestone.acceptance_criteria)

    writer({"agent": "tester", "msg": "Judging acceptance criteria"})

    user_prompt = (
        f"## Acceptance Criteria\n{criteria_text}\n\n"
        f"## Test Output\n```\n{pytest_output[:5000]}\n```\n\n"
        f"## All Files in Workspace\n"
        + "\n".join(f"- {f}" for f in all_files)
        + "\n\n"
        + "\n\n".join(key_contents)
    )

    try:
        test_report, tokens = invoke_structured(
            system_prompt=_load_prompt("tester.md"),
            user_prompt=user_prompt,
            schema=TestReport,
            run_config=state.get("run_config"),
            ledger=ledger,
            agent="tester",
        )
    except BudgetExhaustedError as e:
        return {
            "status": "failed",
            "status_reason": str(e),
            "test_output": pytest_output,
            **ledger.state_update(),
        }
    except Exception:
        return {
            "status": "failed",
            "status_reason": "tester LLM invocation failed",
            "test_output": pytest_output,
            **ledger.state_update(),
        }

    return {
        "test_report": test_report,
        "test_output": pytest_output,
        "file_tree": file_tree(workspace),
        **ledger.state_update(),
    }
