import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from symbiot.graph import builder


def main():
    db_path = Path(__file__).resolve().parent / "checkpoints.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    saver = SqliteSaver(conn)
    graph = builder.compile(checkpointer=saver)

    spec_path = Path(__file__).resolve().parent.parent / "projects" / "example" / "PROJECT.md"
    spec = spec_path.read_text()

    config = {"configurable": {"thread_id": "run-001"}}

    result = graph.invoke({"raw_spec": spec}, config=config)

    while "__interrupt__" in result:
        info = result["__interrupt__"][0].value
        print(f"\n\u26a0\ufe0f  {info['question']}")
        failures = info.get("failures")
        if failures:
            print(f"Failures: {failures}")
        choice = input("Retry or abort? [retry/abort]: ") if failures else input("Deploy or skip? [deploy/skip]: ")
        result = graph.invoke(Command(resume=choice), config=config)

    budget = result.get("budget")
    if budget:
        print(f"budget: tokens_used={budget.tokens_used}, llm_calls={budget.llm_calls}")

    print("status:", result.get("status"))
    reason = result.get("status_reason")
    if reason:
        print("status_reason:", reason)

    print("container_id:", result.get("container_id", ""))
    if result.get("test_report"):
        tr = result["test_report"]
        print("test_report:", {"passed": tr.passed, "confidence": tr.confidence, "failures": tr.failures})

    git_dir = Path(result.get("workspace", "")) / ".git"
    if git_dir.exists():
        print("git repo: yes")
        from symbiot.sandbox.git_ops import get_log
        log = get_log(str(git_dir.parent))
        print("commits:", log)

    deploy = result.get("deploy_result")
    if deploy:
        print(f"deploy: image={deploy.get('image')}:{deploy.get('tag')} smoke={deploy.get('smoke_test_passed')}")


if __name__ == "__main__":
    main()
