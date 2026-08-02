from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import subprocess
from typing import Any
from pydantic import BaseModel, Field

from symbiot.provider_store import ProviderManager, ProviderStoreError
from symbiot.run_manager import RunManager
from symbiot.sandbox.git_ops import rollback as git_rollback
from symbiot.schemas import ModelSelection

PROJECTS_ROOT = Path(__file__).resolve().parents[3] / "projects"
WORKSPACE_ROOT = Path(__file__).resolve().parents[3] / "backend" / "workspace"

app = FastAPI(title="Symbiot Sidecar")
provider_manager = ProviderManager()
run_manager = RunManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def safe(root: Path, name: str) -> Path:
    p = (root / name).resolve()
    if not str(p).startswith(str(root)):
        raise HTTPException(403, "Path traversal blocked")
    return p


def _is_binary(path: Path) -> bool:
    try:
        text = path.read_text()
        return False
    except UnicodeDecodeError:
        return True


class ProviderSaveBody(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    kind: str = Field(min_length=1, max_length=40)
    default_model: str = Field(min_length=1, max_length=200)
    base_url: str | None = None
    label: str | None = Field(default=None, max_length=120)
    models: list[str] = Field(default_factory=list)
    enabled: bool = True
    api_key: str | None = None


class ProviderTestBody(BaseModel):
    model: str | None = None


class ProviderRoutingBody(BaseModel):
    primary: ModelSelection
    fallbacks: list[ModelSelection] = Field(default_factory=list)


class RunStartBody(BaseModel):
    raw_spec: str = Field(min_length=1)
    source_path: str | None = None
    run_config: dict[str, Any] = Field(default_factory=dict)


class RunResumeBody(BaseModel):
    decision: Any


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "symbiot"}


@app.post("/api/runs")
def start_run(body: RunStartBody) -> dict[str, str]:
    session = run_manager.start(body.model_dump())
    return {"run_id": session.run_id, "status": session.status}


@app.get("/api/runs/{run_id}")
def run_status(run_id: str) -> dict[str, Any]:
    session = run_manager.get(run_id)
    if session is None:
        raise HTTPException(404, "run not found")
    return {
        "run_id": session.run_id,
        "status": session.status,
        "waiting_for_human": session.waiting_for_human,
        "event_count": len(session.events),
    }


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str, after: int = 0) -> StreamingResponse:
    if run_manager.get(run_id) is None:
        raise HTTPException(404, "run not found")
    return StreamingResponse(
        run_manager.events(run_id, after=max(0, after)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str, body: RunResumeBody) -> dict[str, Any]:
    try:
        cursor = run_manager.resume(run_id, body.decision)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id, "cursor": cursor, "status": "running"}


@app.get("/providers")
def list_providers() -> list[dict[str, Any]]:
    try:
        return provider_manager.list_public()
    except ProviderStoreError as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/providers")
def save_provider(body: ProviderSaveBody) -> dict[str, Any]:
    try:
        return provider_manager.save(**body.model_dump())
    except ProviderStoreError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/providers/{provider_id}/test")
def test_provider_connection(provider_id: str, body: ProviderTestBody) -> dict[str, Any]:
    try:
        return provider_manager.test_connection(provider_id, body.model)
    except ProviderStoreError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/providers/routing")
def set_provider_routing(body: ProviderRoutingBody) -> dict[str, Any]:
    try:
        config = provider_manager.set_routing(body.primary, body.fallbacks)
    except ProviderStoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    return config.model_dump()


@app.get("/projects")
def list_projects() -> list[dict]:
    results: list[dict] = []
    if not PROJECTS_ROOT.exists():
        return results
    for d in sorted(PROJECTS_ROOT.iterdir()):
        if not d.is_dir():
            continue
        spec_path = d / "PROJECT.md"
        results.append({
            "name": d.name,
            "has_spec": spec_path.exists(),
        })
    return results


@app.get("/projects/{name}/spec")
def get_spec(name: str) -> str:
    p = safe(PROJECTS_ROOT, name)
    spec_path = p / "PROJECT.md"
    if not spec_path.exists():
        raise HTTPException(404, "No PROJECT.md found")
    return spec_path.read_text()


@app.get("/browse")
def browse(path: str = "") -> dict[str, Any]:
    target = Path(path).expanduser().resolve() if path else Path.home()
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "Directory not found")

    dirs: list[str] = []
    files: list[str] = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append(entry.name)
            else:
                files.append(entry.name)
    except PermissionError:
        pass

    has_git = (target / ".git").is_dir()
    has_spec = (target / "PROJECT.md").is_file()

    return {
        "path": str(target),
        "dirs": dirs,
        "files": files,
        "has_git": has_git,
        "has_spec": has_spec,
    }


@app.get("/workspace/{name}/tree")
def workspace_tree(name: str) -> list[dict]:
    ws = safe(WORKSPACE_ROOT, name)
    if not ws.exists():
        raise HTTPException(404, "Workspace not found")

    results: list[dict] = []
    for f in sorted(ws.rglob("*")):
        if any(part.startswith(".") for part in f.parts):
            continue
        if f.is_file():
            rel = str(f.relative_to(ws))
            results.append({
                "path": rel,
                "size": f.stat().st_size,
            })
    return results


@app.get("/workspace/{name}/file")
def workspace_file(name: str, path: str = "") -> str:
    ws = safe(WORKSPACE_ROOT, name)
    fp = safe(ws, path)
    if not fp.exists():
        raise HTTPException(404, "File not found")
    if _is_binary(fp):
        raise HTTPException(400, "Binary file")
    return fp.read_text()


@app.get("/workspace/{name}/git/log")
def git_log(name: str) -> list[dict]:
    ws = safe(WORKSPACE_ROOT, name)
    try:
        out = subprocess.run(
            ["git", "log", "--pretty=format:%H|%h|%s|%cI"],
            cwd=str(ws),
            capture_output=True,
            text=True,
        )
    except Exception:
        raise HTTPException(500, "Git error")
    if not out.stdout.strip():
        return []
    commits: list[dict] = []
    for line in out.stdout.strip().split("\n"):
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0],
                "short": parts[1],
                "message": parts[2],
                "date": parts[3],
            })
    return commits


@app.get("/workspace/{name}/git/diff")
def git_diff(name: str, commit: str = "") -> str:
    ws = safe(WORKSPACE_ROOT, name)
    try:
        out = subprocess.run(
            ["git", "show", commit, "--patch", "--color=never"],
            cwd=str(ws),
            capture_output=True,
            text=True,
        )
    except Exception:
        raise HTTPException(500, "Git error")
    return out.stdout


@app.get("/workspace/{name}/git/status")
def git_status(name: str) -> list[dict]:
    ws = safe(WORKSPACE_ROOT, name)
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ws),
            capture_output=True,
            text=True,
        )
    except Exception:
        raise HTTPException(500, "Git error")
    results: list[dict] = []
    for line in out.stdout.strip().split("\n"):
        if not line.strip():
            continue
        code = line[:2].strip()
        fpath = line[3:].strip()
        results.append({"code": code, "path": fpath})
    return results


@app.post("/workspace/{name}/git/rollback")
def git_rollback_endpoint(name: str, body: dict[str, str]) -> list[dict]:
    ws = safe(WORKSPACE_ROOT, name)
    commit = body.get("commit", "")
    if not commit:
        raise HTTPException(400, "commit is required")
    git_rollback(str(ws), commit)
    return git_log(name)


FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
