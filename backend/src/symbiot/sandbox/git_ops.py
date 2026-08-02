import subprocess
from pathlib import Path

GIT_EMAIL = "symbiot@agent.local"
GIT_NAME = "symbiot"


def _run(cmd: list[str], cwd: str) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip()


def init_repo(path: str) -> None:
    p = Path(path)
    if (p / ".git").exists():
        return
    _run(["git", "init"], path)
    _run(["git", "config", "user.email", GIT_EMAIL], path)
    _run(["git", "config", "user.name", GIT_NAME], path)
    _run(["git", "add", "-A"], path)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "scaffold"],
        cwd=path,
        capture_output=True,
        text=True,
    )


def commit_all(path: str, message: str) -> str:
    _run(["git", "add", "-A"], path)
    r = subprocess.run(
        ["git", "commit", "--allow-empty", "-m", message],
        cwd=path,
        capture_output=True,
        text=True,
    )
    return _run(["git", "rev-parse", "--short", "HEAD"], path)


def get_log(path: str, limit: int = 5) -> list[str]:
    output = _run(["git", "log", f"-{limit}", "--oneline"], path)
    if not output:
        return []
    return output.split("\n")


def rollback(path: str, commit_hash: str) -> None:
    _run(["git", "checkout", commit_hash, "--", "."], path)
    subprocess.run(
        ["git", "commit", "-m", f"rollback to {commit_hash}"],
        cwd=path,
        capture_output=True,
        text=True,
    )
