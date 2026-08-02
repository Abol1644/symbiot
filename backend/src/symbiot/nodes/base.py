import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from symbiot.sandbox.docker_sandbox import Sandbox
from symbiot.sandbox.git_ops import init_repo
from symbiot.state import LoopState


def _parse_deps(stack: str) -> list[str]:
    parts = [p.strip() for p in stack.split(",")]
    deps = [p for p in parts if not re.match(r"^python\s*\d", p, re.IGNORECASE)]
    extra = []
    for d in deps:
        if d.lower() == "fastapi":
            extra.extend(["pytest", "httpx"])
    return deps + extra


def base(state: LoopState) -> dict:
    spec_name = state["spec"].get("name", "project")
    ws_root = Path.home() / ".symbiot" / "workspace"
    workspace = ws_root / spec_name

    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    ws_str = str(workspace)
    init_repo(ws_str)

    stack = state["spec"].get("stack", "")
    deps = _parse_deps(stack)

    if deps:
        req_path = workspace / "requirements.txt"
        req_path.write_text("\n".join(deps) + "\n")

    sandbox = Sandbox(ws_str)
    container_id = sandbox.start()

    if deps:
        sandbox.exec("pip install --no-cache-dir -r requirements.txt")

    return {
        "workspace": ws_str,
        "current": 0,
        "attempts": 0,
        "lessons": [],
        "container_id": container_id,
        "run_started_at": datetime.now(timezone.utc).isoformat(),
    }
