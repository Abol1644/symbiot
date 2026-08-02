from pathlib import Path

import docker
from docker.errors import BuildError, DockerException

from langgraph.config import get_stream_writer

from symbiot.schemas import DeployResult
from symbiot.state import LoopState


def _find_entrypoint(workspace: str, spec: dict) -> str:
    ep = spec.get("entrypoint")
    if ep:
        return ep
    ws = Path(workspace)
    for f in sorted(ws.rglob("*.py")):
        rel = str(f.relative_to(ws))
        if "test_" not in rel:
            return rel
    return "main.py"


def deployer(state: LoopState) -> dict:
    writer = get_stream_writer()
    workspace = state["workspace"]
    spec = state["spec"]
    spec_name = spec.get("name", "project")
    runtime = spec.get("runtime", "cli")
    entrypoint = _find_entrypoint(workspace, spec)
    image_name = f"symbiot-{spec_name}"

    ws_path = Path(workspace)
    has_requirements = (ws_path / "requirements.txt").exists()

    pip_install = ""
    if has_requirements:
        pip_install = "RUN pip install --no-cache-dir -r requirements.txt\n"

    if runtime == "api":
        dockerfile = (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            f"{pip_install}"
            f'CMD ["python", "{entrypoint}"]\n'
        )
    else:
        dockerfile = (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            f"{pip_install}"
            f'ENTRYPOINT ["python", "{entrypoint}"]\n'
        )

    dockerfile_path = ws_path / "Dockerfile"
    dockerfile_path.write_text(dockerfile)

    try:
        client = docker.from_env()
    except DockerException:
        return {"status": "failed", "status_reason": "docker not available"}

    writer({"agent": "deployer", "msg": "Building Docker image"})

    try:
        image, _logs = client.images.build(
            path=str(ws_path),
            tag=f"{image_name}:latest",
            rm=True,
        )
    except BuildError as e:
        return {"status": "failed", "status_reason": f"deploy_build_failed: {e}"}
    except Exception as e:
        return {"status": "failed", "status_reason": f"deploy_build_failed: {e}"}

    writer({"agent": "deployer", "msg": "Running smoke test"})

    smoke_cmd = spec.get("smoke_command", "--help")
    smoke_passed = False
    smoke_output = ""

    try:
        smoke_output = client.containers.run(
            f"{image_name}:latest",
            command=smoke_cmd,
            remove=True,
        )
        smoke_output = smoke_output.decode("utf-8", errors="replace")
        smoke_passed = True
    except Exception as e:
        smoke_output = str(e)

    result = DeployResult(
        image=image_name,
        tag="latest",
        smoke_test_passed=smoke_passed,
        smoke_test_output=smoke_output,
    )

    return {"deploy_result": result.model_dump(), "status": "passed"}
