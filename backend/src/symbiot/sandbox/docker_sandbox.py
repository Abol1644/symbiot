import os
import docker
from docker.errors import NotFound, DockerException


class Sandbox:
    def __init__(self, workspace_path: str, image: str = "symbiot-sandbox"):
        self.workspace_path = os.path.abspath(workspace_path)
        self.image = image
        self.container_id: str | None = None
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException:
                raise RuntimeError("Docker daemon not running — start it and retry.")
        return self._client

    def start(self) -> str:
        try:
            self.client.images.get(self.image)
        except NotFound:
            raise RuntimeError(
                f"Image '{self.image}' not found. "
                "Run: docker build -t symbiot-sandbox backend/sandbox/"
            )

        c = self.client.containers.run(
            self.image,
            command=["sleep", "infinity"],
            volumes={self.workspace_path: {"bind": "/workspace", "mode": "rw"}},
            detach=True,
        )
        self.container_id = c.id
        return c.id

    def exec(self, command: str, timeout: int = 30) -> tuple[str, str, int]:
        if self.container_id is None:
            raise RuntimeError("Container not started. Call start() or reconnect() first.")
        try:
            c = self.client.containers.get(self.container_id)
        except NotFound:
            raise RuntimeError(f"Container {self.container_id} not found")

        full_cmd = f"timeout {timeout} {command}"
        exit_code, raw = c.exec_run(
            ["/bin/sh", "-c", full_cmd],
            workdir="/workspace",
            demux=True,
            socket=False,
        )
        stdout_bytes, stderr_bytes = raw
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        return stdout, stderr, exit_code

    def is_running(self, container_id: str) -> bool:
        try:
            c = self.client.containers.get(container_id)
            return c.status == "running"
        except NotFound:
            return False

    def reconnect(self, container_id: str) -> None:
        try:
            self.client.containers.get(container_id)
        except NotFound:
            raise RuntimeError(f"Container {container_id} not found — it may have been killed.")
        self.container_id = container_id

    def stop(self) -> None:
        if self.container_id is None:
            return
        try:
            c = self.client.containers.get(self.container_id)
            c.kill()
            c.remove()
        except NotFound:
            pass
        finally:
            self.container_id = None
