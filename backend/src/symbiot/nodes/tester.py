from pathlib import Path

from langgraph.config import get_stream_writer

from symbiot.llm import invoke_structured
from symbiot.schemas import TestReport
from symbiot.sandbox.docker_sandbox import Sandbox
from symbiot.sandbox.git_ops import file_tree
from symbiot.state import LoopState
from symbiot.guards import check_budget, update_budget, BudgetExhaustedError, check_run_timeout, RunTimeoutError


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
        return {"status": "failed", "status_reason": str(e)}
    try:
        check_run_timeout(state)
    except RunTimeoutError as e:
        return {"status": "failed", "status_reason": str(e)}

    workspace = state["workspace"]
    milestone = state["milestones"][state["current"]]
    ws_path = Path(workspace)

    artifacts: list[str] = []
    pytest_output = ""

    sandbox = Sandbox(workspace)
    container_id = state.get("container_id", "")
    if container_id:
        try:
            sandbox.reconnect(container_id)
        except RuntimeError:
            pass

    has_tests = bool(_rglob(ws_path, "test_*.py")) or (ws_path / "tests").is_dir()
    if has_tests:
        writer({"agent": "tester", "msg": "Running pytest"})
        try:
            stdout, stderr, exit_code = sandbox.exec("python -m pytest -v", timeout=30)
            pytest_output = stdout + "\n" + stderr
            artifacts.append("pytest output captured")
        except Exception as e:
            pytest_output = str(e)
            artifacts.append("pytest execution error")

    py_files: list[str] = []
    try:
        file_list_raw, _, _ = sandbox.exec("find . -name '*.py'", timeout=10)
        py_files = [f.strip() for f in file_list_raw.split("\n") if f.strip()]
    except Exception:
        py_files = [str(p.relative_to(ws_path)) for p in _rglob(ws_path, "*.py")]

    all_files: list[str] = []
    try:
        all_raw, _, _ = sandbox.exec("find . -type f", timeout=10)
        all_files = [f.strip() for f in all_raw.split("\n") if f.strip()]
    except Exception:
        all_files = py_files

    syntax_errors: list[str] = []
    for f in py_files:
        try:
            _, stderr, exit_code = sandbox.exec(
                f"python -c \"import ast; ast.parse(open('{f}').read())\"",
                timeout=10,
            )
            if exit_code != 0:
                syntax_errors.append(f"{f}: {stderr.strip()[:200]}")
        except Exception:
            pass
    if syntax_errors:
        artifacts.append("syntax errors: " + "; ".join(syntax_errors))

    file_list = py_files
    key_contents: list[str] = []
    for f in py_files[:10]:
        fp = ws_path / f
        try:
            key_contents.append(f"### {f}\n```\n{fp.read_text()[:3000]}\n```")
        except Exception:
            pass

    criteria_text = "\n".join(f"- {c}" for c in milestone.acceptance_criteria)

    writer({"agent": "tester", "msg": "Judging acceptance criteria"})

    user_prompt = (
        f"## Acceptance Criteria\n{criteria_text}\n\n"
        f"## Test Output\n```\n{pytest_output[:5000]}\n```\n\n"
        f"## All Files in Workspace\n" + "\n".join(f"- {f}" for f in all_files) + "\n\n"
        + "\n\n".join(key_contents)
    )

    try:
        test_report, tokens = invoke_structured(
            system_prompt=_load_prompt("tester.md"),
            user_prompt=user_prompt,
            schema=TestReport,
        )
    except Exception:
        return {"status": "failed", "status_reason": "tester LLM invocation failed"}

    budget_update = update_budget(state, tokens, "tester")
    return {"test_report": test_report, "file_tree": file_tree(workspace), **budget_update}
