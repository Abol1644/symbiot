import json
import re
from typing import TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from symbiot.config import Settings

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def get_llm() -> ChatOpenAI:
    s = Settings()
    if s.model_provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=s.model_name)
    return ChatOpenAI(
        model=s.model_name,
        base_url=s.base_url,
        api_key=s.api_key,
        temperature=0,
    )


def _extract_tokens(raw) -> int:
    if raw.usage_metadata:
        return raw.usage_metadata.get("input_tokens", 0) + raw.usage_metadata.get("output_tokens", 0)
    return 1000


def invoke_structured(
    system_prompt: str,
    user_prompt: str,
    schema: type[T],
    max_retries: int = 3,
) -> tuple[T, int]:
    llm = get_llm()
    schema_json = json.dumps(schema.model_json_schema())
    total_tokens = 0

    for attempt in range(max_retries + 1):
        feedback = ""
        if attempt > 0:
            feedback = (
                f"\nYour last response was invalid: {last_error}. Fix it.\n"
            )
        system = (
            f"{system_prompt}\n"
            "Respond with ONLY raw JSON. No markdown fences, no explanation, "
            "no code blocks. The JSON must match this JSON schema:\n"
            f"{schema_json}{feedback}"
        )
        message = llm.invoke(
            [
                ("system", system),
                ("user", user_prompt),
            ]
        )
        total_tokens += _extract_tokens(message)
        text = _strip_fences(message.content)
        try:
            return schema.model_validate_json(text), total_tokens
        except ValidationError as e:
            last_error = e
            if attempt < max_retries:
                continue
            raise ValueError(
                f"Failed to get valid {schema.__name__} after "
                f"{max_retries + 1} attempts: {e}"
            ) from e
    raise ValueError(f"Failed to get valid {schema.__name__}")


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip())
