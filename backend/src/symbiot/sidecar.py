import logging
import secrets
import subprocess
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from symbiot.config import get_workspace_root
from symbiot.provider_store import ProviderManager, ProviderStoreError
from symbiot.redaction import redact_provider_config
from symbiot.run_manager import RunManager
from symbiot.git_ops import rollback as git_rollback
from symbiot.schemas import ModelSelection

logger = logging.getLogger("symbiot.sidecar")

PROJECTS_ROOT = Path(__file__).resolve().parents[3] / "projects"


def workspace_root() -> Path:
    """Resolve the workspace root via the shared backend setting.

    Reads ``Settings`` on every call so ``SYMBIOT_WORKSPACE_ROOT`` overrides
    take effect without reimporting this module.
    """

    return get_workspace_root()


# Backwards-compatible alias for the pre-refactor module constant.
WORKSPACE_ROOT = get_workspace_root()

API_TOKEN = secrets.token_urlsafe(32)
logger.warning("Symbiot sidecar API token: %s", API_TOKEN)

security = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> None:
    if credentials is None or credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )


app = FastAPI(title="Symbiot Sidecar")
provider_manager = ProviderManager()
run_manager = RunManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


def safe(base: Path, target: Path) -> Path:
    resolved_base = base.resolve()
    resolved_target = (resolved_base / target).resolve()
    if not resolved_target.is_relative_to(resolved_base):
        raise ValueError(f"Path escapes workspace: {target}")
    return resolved_target


def _safe(root: Path, name: str) -> Path:
    try:
        return safe(root, Path(name))
    except ValueError as exc:
        raise HTTPException(403, "Path traversal blocked") from exc


def _is_binary(path: Path) -> bool:
    try:
        _ = path.read_text()
        return False
    except UnicodeDecodeError:
        return True


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "symbiot"}


_LOCAL_CLIENT_HOSTS = {"127.0.0.1", "localhost", "::1", "testclient"}


@app.get("/api/auth/token")
def auth_token(request: Request) -> dict[str, str]:
    host = request.client.host if request.client else ""
    if host not in _LOCAL_CLIENT_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token endpoint is localhost-only",
        )
    return {"token": API_TOKEN}


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


@app.post("/api/runs", dependencies=[Depends(require_auth)])
def start_run(body: RunStartBody) -> dict[str, str]:
    session = run_manager.start(body.model_dump())
    return {"run_id": session.run_id, "status": session.status}


@app.get("/api/runs/history", dependencies=[Depends(require_auth)])
def run_history(limit: int = 50) -> list[dict]:
    summaries = run_manager.get_run_history(limit=max(1, min(limit, 200)))
    return [summary.__dict__ for summary in summaries]


@app.get("/api/runs/{run_id}", dependencies=[Depends(require_auth)])
def run_status(run_id: str) -> dict[str, Any]:
    session = run_manager.get(run_id)
    if session is None:
        summary = run_manager.get_run(run_id)
        if summary is None:
            raise HTTPException(404, "run not found")
        return {
            "run_id": summary.run_id,
            "status": summary.status,
            "waiting_for_human": False,
            "event_count": summary.event_count,
        }
    return {
        "run_id": session.run_id,
        "status": session.status,
        "waiting_for_human": session.waiting_for_human,
        "event_count": len(session.events),
    }


@app.get("/api/runs/{run_id}/events", dependencies=[Depends(require_auth)])
def run_events(run_id: str, after_id: int = 0) -> StreamingResponse:
    if run_manager.get(run_id) is None and run_manager.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    return StreamingResponse(
        run_manager.events(run_id, after_id=max(0, after_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/resume", dependencies=[Depends(require_auth)])
def resume_run(run_id: str, body: RunResumeBody) -> dict[str, Any]:
    try:
        cursor = run_manager.resume(run_id, body.decision)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id, "cursor": cursor, "status": "running"}


@app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(require_auth)])
def cancel_run(run_id: str) -> dict[str, str]:
    try:
        status = run_manager.cancel_run(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": status}


@app.delete("/api/runs/expired", dependencies=[Depends(require_auth)])
def delete_expired_runs() -> dict[str, int]:
    deleted = run_manager.cleanup_expired_runs()
    return {"deleted": deleted}


@app.delete("/api/runs/{run_id}", dependencies=[Depends(require_auth)])
def delete_run(run_id: str) -> dict[str, str]:
    try:
        run_manager.delete_run(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": run_id}


@app.get("/providers", dependencies=[Depends(require_auth)])
def list_providers() -> list[dict[str, Any]]:
    try:
        providers = provider_manager.list_public()
    except ProviderStoreError as exc:
        raise HTTPException(500, str(exc)) from exc
    return [redact_provider_config(provider) for provider in providers]


@app.post("/providers", dependencies=[Depends(require_auth)])
def save_provider(body: ProviderSaveBody) -> dict[str, Any]:
    try:
        provider = provider_manager.save(**body.model_dump())
    except ProviderStoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    return redact_provider_config(provider)


@app.post("/providers/{provider_id}/test", dependencies=[Depends(require_auth)])
def test_provider_connection(provider_id: str, body: ProviderTestBody) -> dict[str, Any]:
    try:
        return provider_manager.test_connection(provider_id, body.model)
    except ProviderStoreError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/providers/routing", dependencies=[Depends(require_auth)])
def set_provider_routing(body: ProviderRoutingBody) -> dict[str, Any]:
    try:
        config = provider_manager.set_routing(body.primary, body.fallbacks)
    except ProviderStoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    return config.model_dump()


@app.get("/projects", dependencies=[Depends(require_auth)])
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


@app.get("/projects/{name}/spec", dependencies=[Depends(require_auth)])
def get_spec(name: str) -> str:
    p = _safe(PROJECTS_ROOT, name)
    spec_path = p / "PROJECT.md"
    if not spec_path.exists():
        raise HTTPException(404, "No PROJECT.md found")
    return spec_path.read_text()


@app.get("/browse", dependencies=[Depends(require_auth)])
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


@app.get("/workspace/{name}/tree", dependencies=[Depends(require_auth)])
def workspace_tree(name: str) -> list[dict]:
    ws = _safe(workspace_root(), name)
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


@app.get("/workspace/{name}/file", dependencies=[Depends(require_auth)])
def workspace_file(name: str, path: str = "") -> str:
    ws = _safe(workspace_root(), name)
    fp = _safe(ws, path)
    if not fp.exists():
        raise HTTPException(404, "File not found")
    if _is_binary(fp):
        raise HTTPException(400, "Binary file")
    return fp.read_text()


@app.get("/workspace/{name}/git/log", dependencies=[Depends(require_auth)])
def git_log(name: str) -> list[dict]:
    ws = _safe(workspace_root(), name)
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


@app.get("/workspace/{name}/git/diff", dependencies=[Depends(require_auth)])
def git_diff(name: str, commit: str = "") -> str:
    ws = _safe(workspace_root(), name)
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


@app.get("/workspace/{name}/git/status", dependencies=[Depends(require_auth)])
def git_status(name: str) -> list[dict]:
    ws = _safe(workspace_root(), name)
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


@app.post("/workspace/{name}/git/rollback", dependencies=[Depends(require_auth)])
def git_rollback_endpoint(name: str, body: dict[str, str]) -> list[dict]:
    ws = _safe(workspace_root(), name)
    commit = body.get("commit", "")
    if not commit:
        raise HTTPException(400, "commit is required")
    git_rollback(str(ws), commit)
    return git_log(name)


FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
