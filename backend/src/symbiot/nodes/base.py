import os
import re
import shutil
from datetime import datetime, UTC
from pathlib import Path

from langgraph.config import get_stream_writer

from symbiot.config import get_workspace_root
from symbiot.git_ops import init_repo, commit_all, file_tree
from symbiot.state import LoopState

_EXCLUDE_PATTERNS = shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".venv", "*.pyc")

PROJECTS_ROOT = Path(
    os.getenv("SYMBIOT_PROJECTS_DIR", str(Path(__file__).resolve().parents[4] / "projects"))
)


def sanitize_project_name(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip())
    clean = re.sub(r"_+", "_", clean)
    if not clean or clean in (".", "..", "...", "____"):
        raise ValueError(f"Invalid project name: {name!r}")
    return clean[:64]


def resolve_source_path(source_path: str | None) -> str | None:
    if not source_path:
        return None
    root = PROJECTS_ROOT.resolve()
    candidate = Path(source_path)
    if candidate.is_absolute():
        raise ValueError(f"source_path must be relative: {source_path!r}")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"source_path escapes projects directory: {source_path!r}")
    return str(resolved)


def base(state: LoopState) -> dict:
    writer = get_stream_writer()
    writer({"agent": "base", "msg": "Initializing workspace"})

    spec = dict(state.get("spec") or {})
    spec_name = sanitize_project_name(spec.get("name", "project"))
    spec["name"] = spec_name
    ws_root = get_workspace_root()
    workspace = ws_root / spec_name

    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    ws_str = str(workspace)
    source_path = resolve_source_path(state.get("source_path"))

    if source_path:
        writer({"agent": "base", "msg": f"Importing from {Path(source_path).name}"})
        shutil.copytree(source_path, ws_str, dirs_exist_ok=True, ignore=_EXCLUDE_PATTERNS)
        init_repo(ws_str)
        commit_all(ws_str, f"imported from {Path(source_path).name}")
    else:
        init_repo(ws_str)

    return {
        "workspace": ws_str,
        "spec": spec,
        "current": 0,
        "attempts": 0,
        "lessons": [],
        "run_started_at": datetime.now(UTC).isoformat(),
        "file_tree": file_tree(ws_str),
    }
