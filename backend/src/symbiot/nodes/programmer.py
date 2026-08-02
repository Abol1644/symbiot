import re
import shlex
from pathlib import Path

from langgraph.config import get_stream_writer

from symbiot.llm import invoke_structured
from symbiot.providers import redact_sensitive_text
from symbiot.schemas import FileContent
from symbiot.sandbox.docker_sandbox import Sandbox
from symbiot.sandbox.git_ops import file_tree
from symbiot.state import LoopState
from symbiot.guards import BudgetLedger, BudgetExhaustedError, RunTimeoutError, check_budget, check_run_timeout


def _load_prompt(filename: str) -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / filename
    return path.read_text()


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _is_safe_command(cmd: str, workspace: str) -> bool:
    if "sudo" in cmd:
        return False
    if re.search(r"\brm\s+-rf\s+/", cmd):
        return False
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return False
    for token in tokens:
        if token.startswith("/") and not token.startswith(workspace + "/"):
            return False
    return True


def _get_sandbox(workspace: str, container_id: str) -> tuple[Sandbox, str | None]:
    sandbox = Sandbox(workspace)
    if container_id:
        try:
            sandbox.reconnect(container_id)
            return sandbox, None
        except RuntimeError:
            pass
    new_id = sandbox.start()
    return sandbox, new_id


def programmer(state: LoopState) -> dict:
    writer = get_stream_writer()
    try:
        check_budget(state)
    except BudgetExhaustedError as e:
        return {"status": "failed", "status_reason": str(e)}
    try:
        check_run_timeout(state)
    except RunTimeoutError as e:
        return {"status": "failed", "status_reason": str(e)}

    ledger = BudgetLedger(state)

    plan = state.get("plan")
    workspace = state["workspace"]
    attempts = state["attempts"]
    current_cid = state.get("container_id", "")
    updated_container_id: str | None = None
    if plan is None:
        return {
            "attempts": attempts + 1,
            "status": "failed",
            "status_reason": "no plan",
            **ledger.state_update(),
        }

    writer({"agent": "programmer", "msg": "Starting plan execution"})

    for step in plan.steps:
        action = step.action
        target = step.target
        detail = step.detail
        content = step.content

        writer({"agent": "programmer", "msg": f"{action}: {target}"})

        if action == "create_file":
            file_content = content or detail
            _write_file(Path(workspace) / target, file_content)

        elif action == "edit_file":
            fp = Path(workspace) / target
            current_content = fp.read_text() if fp.exists() else ""
            user_prompt = f"## Current file content\n```\n{current_content}\n```\n\n## Edit instruction\n{detail}\n\nReturn the complete modified file content."
            try:
                result, tokens = invoke_structured(
                    system_prompt=_load_prompt("programmer.md"),
                    user_prompt=user_prompt,
                    schema=FileContent,
                    run_config=state.get("run_config"),
                    ledger=ledger,
                    agent="programmer",
                )
                _write_file(fp, result.content)
            except BudgetExhaustedError as e:
                return {
                    "attempts": attempts + 1,
                    "status": "failed",
                    "status_reason": str(e),
                    **ledger.state_update(),
                }
            except Exception:
                continue

        elif action == "run_command":
            if not _is_safe_command(detail, workspace):
                continue
            try:
                sandbox, new_id = _get_sandbox(workspace, current_cid)
                if new_id:
                    updated_container_id = new_id
                    current_cid = new_id
                stdout, stderr, exit_code = sandbox.exec(detail)
                if stdout:
                    writer({
                        "agent": "programmer",
                        "kind": "stdout",
                        "msg": redact_sensitive_text(stdout, limit=6000),
                    })
                if stderr:
                    writer({
                        "agent": "programmer",
                        "kind": "stderr",
                        "msg": redact_sensitive_text(stderr, limit=6000),
                    })
                if exit_code != 0:
                    writer({
                        "agent": "programmer",
                        "kind": "stderr",
                        "msg": f"command exited with code {exit_code}",
                    })
            except Exception:
                pass

        elif action == "delete_file":
            fp = Path(workspace) / target
            if fp.exists():
                fp.unlink()

    result: dict = {"attempts": attempts + 1}
    if updated_container_id:
        result["container_id"] = updated_container_id
    result.update(ledger.state_update())
    result["file_tree"] = file_tree(workspace)
    return result
