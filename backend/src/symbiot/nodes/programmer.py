import logging
import re
import shlex
import subprocess
from pathlib import Path

from langgraph.config import get_stream_writer

from symbiot.llm import invoke_structured
from symbiot.providers import redact_sensitive_text
from symbiot.redaction import redact_secrets
from symbiot.schemas import FileContent
from symbiot.git_ops import file_tree
from symbiot.state import LoopState
from symbiot.guards import BudgetLedger, BudgetExhaustedError, RunTimeoutError, check_budget, check_run_timeout

logger = logging.getLogger(__name__)


def _load_prompt(filename: str) -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / filename
    return path.read_text()


def validate_workspace_target(workspace: Path, target: str) -> Path:
    resolved = (workspace / target).resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise ValueError(f"Target escapes workspace: {target}")
    if Path(target).is_absolute() or ".." in Path(target).parts:
        raise ValueError(f"Invalid target: {target}")
    return resolved


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
    ws_resolved = Path(workspace).resolve()
    for token in tokens:
        candidate = Path(token)
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            return False
        if not resolved.is_relative_to(ws_resolved):
            return False
    return True


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
            try:
                fp = validate_workspace_target(Path(workspace), target)
            except ValueError:
                logger.warning("Rejected %s target: %r", action, target)
                raise
            file_content = content or detail
            _write_file(fp, file_content)

        elif action == "edit_file":
            try:
                fp = validate_workspace_target(Path(workspace), target)
            except ValueError:
                logger.warning("Rejected %s target: %r", action, target)
                raise
            current_content = fp.read_text() if fp.exists() else ""
            try:
                result, tokens = invoke_structured(
                    system_prompt=_load_prompt("programmer.md"),
                    user_prompt=(
                        f"## Current file content\n```\n{redact_secrets(current_content)}\n```\n\n"
                        f"## Edit instruction\n{detail}\n\nReturn the complete modified file content."
                    ),
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
                result = subprocess.run(
                    shlex.split(detail),
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                stdout = result.stdout or ""
                stderr = result.stderr or ""
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
                if result.returncode != 0:
                    writer({
                        "agent": "programmer",
                        "kind": "stderr",
                        "msg": f"command exited with code {result.returncode}",
                    })
            except Exception:
                pass

        elif action == "delete_file":
            try:
                fp = validate_workspace_target(Path(workspace), target)
            except ValueError:
                logger.warning("Rejected %s target: %r", action, target)
                raise
            if fp.exists():
                fp.unlink()

    result: dict = {"attempts": attempts + 1}
    result.update(ledger.state_update())
    result["file_tree"] = file_tree(workspace)
    return result
