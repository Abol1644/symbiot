import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from langgraph.config import get_stream_writer

from symbiot.sandbox.docker_sandbox import Sandbox
from symbiot.sandbox.git_ops import init_repo, commit_all, file_tree
from symbiot.state import LoopState

_EXCLUDE_PATTERNS = shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".venv", "*.pyc")


def _parse_deps(stack: str) -> list[str]:
    parts = [p.strip() for p in stack.split(",")]
    deps = [p for p in parts if not re.match(r"^python\s*\d", p, re.IGNORECASE)]
    extra = []
    for d in deps:
        if d.lower() == "fastapi":
            extra.extend(["pytest", "httpx"])
    return deps + extra


def base(state: LoopState) -> dict:
    writer = get_stream_writer()
    writer({"agent": "base", "msg": "Initializing workspace"})

    spec_name = state["spec"].get("name", "project")
    ws_root = Path.home() / ".symbiot" / "workspace"
    workspace = ws_root / spec_name

    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    ws_str = str(workspace)
    source_path = state.get("source_path")

    if source_path:
        writer({"agent": "base", "msg": f"Importing from {Path(source_path).name}"})
        shutil.copytree(source_path, ws_str, dirs_exist_ok=True, ignore=_EXCLUDE_PATTERNS)
        init_repo(ws_str)
        commit_all(ws_str, f"imported from {Path(source_path).name}")
    else:
        init_repo(ws_str)

    stack = state["spec"].get("stack", "")
    deps = _parse_deps(stack)

    if deps:
        req_path = workspace / "requirements.txt"
        req_path.write_text("\n".join(deps) + "\n")

    sandbox = Sandbox(ws_str)
    container_id = sandbox.start()

    if deps:
        writer({"agent": "base", "msg": "Installing dependencies"})
        sandbox.exec("pip install --no-cache-dir -r requirements.txt")

    return {
        "workspace": ws_str,
        "current": 0,
        "attempts": 0,
        "lessons": [],
        "container_id": container_id,
        "run_started_at": datetime.now(timezone.utc).isoformat(),
        "file_tree": file_tree(ws_str),
    }
