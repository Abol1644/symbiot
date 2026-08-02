"""Symbiot launcher — one command boots graph, sidecar, and frontend."""

import subprocess
import signal
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SERVICES: list[tuple[str, str, str]] = [
    ("graph",    "uv run langgraph dev",    str(ROOT / "backend")),
    ("sidecar",  "uv run uvicorn symbiot.sidecar:app --port 8100 --reload", str(ROOT / "backend")),
    ("frontend", "npm run dev",             str(ROOT / "frontend")),
]

procs: list[tuple[str, subprocess.Popen]] = []

for name, cmd, cwd in SERVICES:
    p = subprocess.Popen(cmd, cwd=cwd, shell=True, preexec_fn=None)
    procs.append((name, p))
    print(f"  [{name}] started (pid {p.pid})")

time.sleep(4)
webbrowser.open("http://localhost:5173")
print("  all services up — http://localhost:5173")
print("  press Ctrl+C to stop\n")


def shutdown(*_):
    print("\n  shutting down...")
    for name, p in procs:
        p.terminate()
    for name, p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    print("  all stopped")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

for name, p in procs:
    p.wait()
