from pathlib import Path

from symbiot.graph import graph

spec_path = Path(__file__).resolve().parent.parent / "projects" / "example" / "PROJECT.md"
spec = spec_path.read_text()

result = graph.invoke(
    {"raw_spec": spec},
    config={"configurable": {"thread_id": "test-1"}},
)
print("status:", result.get("status"))
print("attempts:", result.get("attempts"))
print("current milestone:", result.get("current"))
print("lessons:", result.get("lessons"))
if result.get("test_report"):
    print("test_report:", dict(result["test_report"]))
