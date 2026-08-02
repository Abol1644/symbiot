# backend/test_model.py — run with: uv run python test_model.py
from symbiot.llm import invoke_structured
from symbiot.schemas import Plan

result = invoke_structured(
    system_prompt="You are a planning agent that produces structured plans.",
    user_prompt="Create a 2-step plan to build a hello world CLI in Python. milestone_id is m1.",
    schema=Plan,
)
print(result)
