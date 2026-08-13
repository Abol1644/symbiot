"""Security gate tests: path containment, sanitization, auth, and SSRF."""

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from symbiot import sidecar
from symbiot.nodes import base as base_node
from symbiot.nodes.programmer import validate_workspace_target
from symbiot.providers import validate_provider_url


# ---------------------------------------------------------------------------
# Section 1: path containment in sidecar.safe
# ---------------------------------------------------------------------------

def test_safe_accepts_normal_paths(tmp_path: Path) -> None:
    result = sidecar.safe(tmp_path, Path("app/main.py"))
    assert result == (tmp_path / "app" / "main.py").resolve()


def test_safe_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        sidecar.safe(tmp_path, Path("../../etc/passwd"))


def test_safe_rejects_absolute_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        sidecar.safe(tmp_path, Path("/etc/passwd"))


def test_safe_rejects_symlinks_pointing_outside(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("top secret")
    link = tmp_path / "escape"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        sidecar.safe(tmp_path, Path("escape/secret.txt"))


def test_safe_accepts_normalized_dotdot_inside_root(tmp_path: Path) -> None:
    (tmp_path / "inner").mkdir()
    result = sidecar.safe(tmp_path, Path("inner/../app.py"))
    assert result == (tmp_path / "app.py").resolve()


def test_safe_endpoints_reject_traversal_as_403() -> None:
    client = TestClient(sidecar.app)
    headers = {"Authorization": f"Bearer {sidecar.API_TOKEN}"}
    with pytest.raises(HTTPException) as excinfo:
        sidecar._safe(sidecar.PROJECTS_ROOT, "../etc")
    assert excinfo.value.status_code == 403
    response = client.get(
        "/workspace/foo/file?path=../../etc/passwd",
        headers=headers,
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Section 2: project name sanitization
# ---------------------------------------------------------------------------

def test_sanitize_project_name_keeps_safe_names() -> None:
    assert base_node.sanitize_project_name("todo-cli") == "todo-cli"
    assert base_node.sanitize_project_name("My App") == "My_App"
    assert base_node.sanitize_project_name("a_b-2") == "a_b-2"


def test_sanitize_project_name_neutralizes_traversal() -> None:
    sanitized = base_node.sanitize_project_name("../../etc")
    assert "/" not in sanitized
    assert sanitized not in (".", "..")
    assert Path(sanitized).is_absolute() is False


def test_sanitize_project_name_rejects_empty() -> None:
    with pytest.raises(ValueError, match="Invalid project name"):
        base_node.sanitize_project_name("")
    with pytest.raises(ValueError, match="Invalid project name"):
        base_node.sanitize_project_name("   ")


def test_sanitize_project_name_truncates_long_names() -> None:
    result = base_node.sanitize_project_name("x" * 100)
    assert len(result) == 64


# ---------------------------------------------------------------------------
# Section 3: workspace target validation in programmer
# ---------------------------------------------------------------------------

def test_workspace_target_accepts_relative_paths(tmp_path: Path) -> None:
    result = validate_workspace_target(tmp_path, "src/main.py")
    assert result == (tmp_path / "src" / "main.py").resolve()


def test_workspace_target_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        validate_workspace_target(tmp_path, "../outside.py")


def test_workspace_target_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        validate_workspace_target(tmp_path, "/etc/passwd")


def test_workspace_target_rejects_deep_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        validate_workspace_target(tmp_path, "subdir/../../../etc/shadow")


def test_workspace_target_rejects_dotdot_component(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        validate_workspace_target(tmp_path, "..")


# ---------------------------------------------------------------------------
# Section 4: source_path validation in base
# ---------------------------------------------------------------------------

def test_source_path_none_skips_copy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(base_node, "PROJECTS_ROOT", tmp_path)
    assert base_node.resolve_source_path(None) is None
    assert base_node.resolve_source_path("") is None


def test_source_path_relative_inside_root_passes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(base_node, "PROJECTS_ROOT", tmp_path)
    project = tmp_path / "example"
    project.mkdir()
    assert base_node.resolve_source_path("example") == str(project.resolve())
    assert base_node.resolve_source_path("example/.") == str(project.resolve())


def test_source_path_absolute_rejected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(base_node, "PROJECTS_ROOT", tmp_path)
    with pytest.raises(ValueError, match="must be relative"):
        base_node.resolve_source_path(str(tmp_path / "example"))


def test_source_path_traversal_rejected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(base_node, "PROJECTS_ROOT", tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        base_node.resolve_source_path("../../etc")
    with pytest.raises(ValueError, match="escapes"):
        base_node.resolve_source_path("example/../../etc")


# ---------------------------------------------------------------------------
# Section 5: token auth on the sidecar
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(sidecar.app)


def test_health_requires_no_auth(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_protected_endpoints_return_401_without_token(client: TestClient) -> None:
    assert client.get("/api/runs/missing").status_code == 401
    assert client.post("/api/runs", json={"raw_spec": "x"}).status_code == 401
    assert client.get("/api/runs/missing/events").status_code == 401
    assert client.get("/providers").status_code == 401
    assert client.post("/providers", json={}).status_code == 401
    assert client.get("/projects").status_code == 401
    assert client.get("/projects/example/spec").status_code == 401
    assert client.get("/browse").status_code == 401
    assert client.get("/workspace/foo/tree").status_code == 401
    assert client.get("/workspace/foo/file").status_code == 401
    assert client.get("/workspace/foo/git/log").status_code == 401
    assert client.get("/workspace/foo/git/diff").status_code == 401
    assert client.get("/workspace/foo/git/status").status_code == 401
    assert client.post("/workspace/foo/git/rollback", json={"commit": "x"}).status_code == 401


def test_wrong_token_rejected(client: TestClient) -> None:
    headers = {"Authorization": "Bearer not-the-token"}
    assert client.get("/api/runs/missing", headers=headers).status_code == 401


def test_valid_token_grants_access(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {sidecar.API_TOKEN}"}
    response = client.get("/api/runs/missing", headers=headers)
    assert response.status_code == 404  # auth passed; endpoint reached
    response = client.get("/browse", headers=headers)
    assert response.status_code == 200
    response = client.get("/api/runs/missing/events", headers=headers)
    assert response.status_code == 404  # SSE endpoint also requires auth


def test_token_endpoint_returns_shared_token(client: TestClient) -> None:
    response = client.get("/api/auth/token")
    assert response.status_code == 200
    assert response.json()["token"] == sidecar.API_TOKEN


# ---------------------------------------------------------------------------
# Section 6: SSRF protection for provider URLs
# ---------------------------------------------------------------------------

def test_ssrf_public_https_url_passes() -> None:
    validate_provider_url("https://api.openai.com/v1", "openai")


def test_ssrf_rejects_metadata_ip() -> None:
    with pytest.raises(ValueError, match="Metadata IP"):
        validate_provider_url("https://169.254.169.254/latest/meta-data", "openai")


def test_ssrf_rejects_private_ranges() -> None:
    with pytest.raises(ValueError, match="Blocked IP range"):
        validate_provider_url("https://192.168.1.10/v1", "openai")
    with pytest.raises(ValueError, match="Blocked IP range"):
        validate_provider_url("https://10.0.0.5/v1", "openai")
    with pytest.raises(ValueError, match="Blocked IP range"):
        validate_provider_url("https://127.0.0.1:11434/v1", "generic")


def test_ssrf_rejects_insecure_scheme_for_remote_providers() -> None:
    with pytest.raises(ValueError, match="Insecure scheme"):
        validate_provider_url("http://api.openai.com/v1", "openai")


def test_ssrf_allows_http_for_local_providers() -> None:
    validate_provider_url("http://localhost:11434/v1", "ollama")
    validate_provider_url("http://127.0.0.1:11434/v1", "vllm")


def test_ssrf_rejects_generic_localhost() -> None:
    with pytest.raises(ValueError, match="Insecure scheme"):
        validate_provider_url("http://localhost:11434/v1", "generic")
    with pytest.raises(ValueError, match="Blocked IP range"):
        validate_provider_url("https://localhost:11434/v1", "generic")


def test_ssrf_rejects_blocked_hostnames() -> None:
    with pytest.raises(ValueError, match="Blocked hostname"):
        validate_provider_url("https://api.internal.example/v1", "openai")
    with pytest.raises(ValueError, match="Blocked hostname"):
        validate_provider_url("https://service.local/v1", "openai")
    with pytest.raises(ValueError, match="Blocked hostname"):
        validate_provider_url("https://api.metadata.test/v1", "openai")


def test_ssrf_rejects_missing_hostname() -> None:
    with pytest.raises(ValueError, match="No hostname"):
        validate_provider_url("https:///v1", "openai")


def test_ssrf_provider_creation_validates_real_outbound_urls() -> None:
    with pytest.raises(ValueError, match="Metadata IP"):
        validate_provider_url("https://169.254.169.254/v1", "anthropic")
