"""Regression test: the base node and the sidecar share one workspace root."""

import shutil
from pathlib import Path

from symbiot import sidecar
from symbiot.config import get_workspace_root
from symbiot.nodes import base as base_node


def test_default_workspace_root_is_home_symbiot(monkeypatch) -> None:
    monkeypatch.delenv("SYMBIOT_WORKSPACE_ROOT", raising=False)
    expected = (Path.home() / ".symbiot" / "workspace").resolve()
    assert get_workspace_root() == expected
    assert sidecar.workspace_root() == expected


def test_workspace_root_env_override(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "custom-ws"
    monkeypatch.setenv("SYMBIOT_WORKSPACE_ROOT", str(target))
    assert get_workspace_root() == target.resolve()
    assert sidecar.workspace_root() == target.resolve()


def test_base_node_writes_under_sidecar_workspace_root(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "ws"
    monkeypatch.setenv("SYMBIOT_WORKSPACE_ROOT", str(root))
    monkeypatch.setattr(base_node, "get_stream_writer", lambda: (lambda _payload: None))
    result = base_node.base({"spec": {"name": "audit-probe"}, "source_path": None})
    try:
        assert Path(result["workspace"]) == root.resolve() / "audit-probe"
        assert Path(result["workspace"]).is_dir()
        assert Path(result["workspace"]).resolve().is_relative_to(sidecar.workspace_root())
    finally:
        shutil.rmtree(root, ignore_errors=True)
