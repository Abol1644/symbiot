"""Structured LLM helpers built on the provider abstraction."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, TypeVar

from pydantic import BaseModel, ValidationError

from symbiot.config import Settings
from symbiot.providers import (
    BUILTIN_PROVIDER_DEFINITIONS,
    InvocationUsage,
    ProviderDefinition,
    ProviderRegistry,
    ProviderRouter,
    ProviderUsage,
    normalize_run_config,
)
from symbiot.provider_store import ProviderStore
from symbiot.vault import LocalKeyVault

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _registry(
    settings: Settings | None = None,
    run_config: Mapping[str, Any] | None = None,
) -> ProviderRegistry:
    selected = settings or Settings()
    definitions = dict(BUILTIN_PROVIDER_DEFINITIONS)
    definitions.update(ProviderStore().definitions())
    provider_id = selected.model_provider
    kind = provider_id.lower().replace("-", "_")
    if kind in {"ollama", "vllm", "generic", "openai_compatible"}:
        kind = "generic"
    base_url = selected.base_url or {
        "ollama": "http://localhost:11434/v1",
        "vllm": "http://localhost:8000/v1",
    }.get(provider_id.lower())
    existing = definitions.get(provider_id)
    if existing is None:
        definitions[provider_id] = ProviderDefinition(
            id=provider_id,
            kind=kind,
            default_model=selected.model_name or "local-model",
            base_url=base_url,
            label=provider_id,
        )
    elif base_url:
        definitions[provider_id] = ProviderDefinition(
            id=existing.id,
            kind=existing.kind,
            default_model=selected.model_name or existing.default_model,
            base_url=base_url,
            label=existing.label,
            enabled=existing.enabled,
            models=existing.models,
        )
    normalized = normalize_run_config(run_config)
    for selection in [normalized.primary, *normalized.fallbacks]:
        if selection.provider in definitions:
            continue
        provider_kind = selection.provider.lower().replace("-", "_")
        default_url = {
            "ollama": "http://localhost:11434/v1",
            "vllm": "http://localhost:8000/v1",
        }.get(provider_kind)
        definitions[selection.provider] = ProviderDefinition(
            id=selection.provider,
            kind="generic" if provider_kind in {"ollama", "vllm", "generic"} else provider_kind,
            default_model=selection.model,
            base_url=default_url,
            label=selection.provider,
        )
    return ProviderRegistry(
        definitions=definitions,
        vault=LocalKeyVault(),
        settings=selected,
    )


def get_llm(run_config: Mapping[str, Any] | None = None) -> ProviderRouter:
    """Return the provider router used by agent logic.

    ``run_config`` is accepted here so callers can explicitly select a model,
    while the router still supports the environment-backed default config.
    """

    return ProviderRouter(_registry(run_config=run_config))


def _extract_tokens(raw: Any) -> int:
    """Compatibility helper for callers that only need a token total."""

    if isinstance(raw, ProviderUsage):
        return raw.total_tokens
    usage = getattr(raw, "usage", None)
    if isinstance(usage, ProviderUsage):
        return usage.total_tokens
    if isinstance(usage, Mapping):
        return int(usage.get("total_tokens", 0) or 0)
    return 0


def invoke_structured(
    system_prompt: str,
    user_prompt: str,
    schema: type[T],
    max_retries: int = 3,
    *,
    run_config: Mapping[str, Any] | None = None,
    ledger: Any | None = None,
    agent: str = "unknown",
    router: ProviderRouter | None = None,
) -> tuple[T, InvocationUsage]:
    """Invoke a selected provider and validate its JSON response.

    Provider retries/fallbacks happen inside ``ProviderRouter``.  Validation
    retries remain a separate structured-output concern and are included in
    the returned usage object.
    """

    active_router = router or get_llm(run_config)
    normalized_config = normalize_run_config(run_config)
    schema_json = json.dumps(schema.model_json_schema())
    usage = InvocationUsage()
    last_error = ""

    for attempt in range(max_retries + 1):
        feedback = ""
        if attempt > 0:
            feedback = f"\nYour last response was invalid: {last_error}. Fix it.\n"
        system = (
            f"{system_prompt}\n"
            "Respond with ONLY raw JSON. No markdown fences, no explanation, "
            "no code blocks. The JSON must match this JSON schema:\n"
            f"{schema_json}{feedback}"
        )
        response = active_router.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            run_config=normalized_config,
            ledger=ledger,
        )
        usage.add(response.usage)
        if ledger is not None:
            ledger.record_usage(response.usage, agent)
        text = _strip_fences(response.content)
        try:
            return schema.model_validate_json(text), usage
        except ValidationError as exc:
            last_error = str(exc)
            if attempt >= max_retries:
                raise ValueError(
                    f"Failed to get valid {schema.__name__} after "
                    f"{max_retries + 1} attempts: {exc}"
                ) from exc

    raise ValueError(f"Failed to get valid {schema.__name__}")


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip())
