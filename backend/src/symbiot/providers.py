"""Provider-agnostic model access for symbiot.

Agent nodes depend on ``ProviderRouter`` rather than on an SDK.  The HTTP
adapters deliberately keep credentials in process memory and never include
them in response objects, run state, or error messages.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence, runtime_checkable

import httpx

from symbiot.config import Settings
from symbiot.schemas import ModelSelection, RunConfig


ChatMessage = Mapping[str, str]


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider: str
    context_window: int | None = None
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0


@dataclass(frozen=True)
class ProviderUsage:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ChatResponse:
    content: str
    usage: ProviderUsage


@dataclass(frozen=True)
class StreamChunk:
    delta: str
    done: bool = False
    usage: ProviderUsage | None = None


@dataclass
class InvocationUsage:
    """Usage for one structured invocation, including validation retries."""

    calls: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    tokens_by_provider: dict[str, int] = field(default_factory=dict)
    cost_by_provider: dict[str, float] = field(default_factory=dict)

    def add(self, usage: ProviderUsage) -> None:
        self.calls += 1
        self.total_tokens += usage.total_tokens
        self.cost_usd += usage.cost_usd
        self.tokens_by_provider[usage.provider] = (
            self.tokens_by_provider.get(usage.provider, 0) + usage.total_tokens
        )
        self.cost_by_provider[usage.provider] = (
            self.cost_by_provider.get(usage.provider, 0.0) + usage.cost_usd
        )


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    kind: str
    default_model: str
    base_url: str | None = None
    label: str | None = None
    enabled: bool = True
    models: tuple[str, ...] = ()
    is_default: bool = False
    fallback_order: int | None = None


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter_seconds: float = 0.25


class ProviderError(RuntimeError):
    """A safe, provider-facing error with no credential material."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(_sanitize_error(message))

    @property
    def retryable(self) -> bool:
        return self.status_code == 429 or (
            self.status_code is not None and 500 <= self.status_code <= 599
        )


class ProviderChainError(ProviderError):
    """Raised after every configured provider has failed."""

    def __init__(self, failures: Sequence[tuple[str, str]]) -> None:
        self.failures = tuple(failures)
        detail = "; ".join(f"{provider}: {message}" for provider, message in failures)
        super().__init__(
            f"all configured providers failed ({detail})",
            provider="provider-chain",
        )


class ProviderConfigurationError(ProviderError):
    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider)


@runtime_checkable
class Provider(Protocol):
    name: str

    def chat(
        self,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """Send a non-streaming chat request."""

    def stream(
        self,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> Iterator[StreamChunk]:
        """Yield text deltas and a final usage chunk."""

    def count_tokens(
        self,
        messages: Sequence[ChatMessage],
        model: str | None = None,
    ) -> int:
        """Return a conservative token estimate before a request."""

    def model_list(self) -> list[ModelInfo]:
        """Return models available from the provider."""


_SECRET_RE = re.compile(r"(?:sk|key|token)[-_][A-Za-z0-9_-]{3,}", re.IGNORECASE)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|access[_-]?token|password|secret)"
    r"\s*[:=]\s*(['\"]?)([^\s,'\"]+)\2"
)


def _sanitize_error(message: str) -> str:
    """Keep provider errors useful while preventing accidental key leakage."""

    safe = _SECRET_RE.sub("[redacted]", str(message))
    return safe[:500]


def redact_sensitive_text(value: str, *, limit: int | None = None) -> str:
    """Redact common credential-shaped values before they enter events/state."""

    redacted = _ASSIGNMENT_SECRET_RE.sub(r"\1=[redacted]", value)
    redacted = _SECRET_RE.sub("[redacted]", redacted)
    return redacted[:limit] if limit is not None else redacted


def mask_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "[redacted]"
    return f"{value[:3]}...{value[-4:]}"


def validate_api_key(provider: str, value: str) -> None:
    """Validate the minimum recognizable shape without overfitting key lengths."""

    key = value.strip()
    if not key or key != value or any(ch.isspace() for ch in key):
        raise ValueError("API key must be non-empty and contain no whitespace")

    normalized = provider.lower().replace("-", "_")
    patterns = {
        "anthropic": r"sk-ant-[A-Za-z0-9_-]{3,}",
        "openai": r"sk-(?:proj-)?[A-Za-z0-9_-]{3,}",
        "openrouter": r"sk-or-[A-Za-z0-9_-]{3,}",
        "opencode": r"(?:sk-[A-Za-z0-9_-]{3,}|opencode-[A-Za-z0-9_-]{3,})",
        "opencode_ai": r"(?:sk-[A-Za-z0-9_-]{3,}|opencode-[A-Za-z0-9_-]{3,})",
    }
    pattern = patterns.get(normalized, r"[A-Za-z0-9_./+=:-]{8,}")
    if not re.fullmatch(pattern, key):
        raise ValueError(f"API key format is invalid for provider '{provider}'")


def _estimate_tokens(messages: Sequence[ChatMessage], content: str = "") -> tuple[int, int]:
    input_chars = sum(len(str(m.get("role", ""))) + len(str(m.get("content", ""))) for m in messages)
    input_tokens = max(1, math.ceil(input_chars / 4))
    output_tokens = max(0, math.ceil(len(content) / 4))
    return input_tokens, output_tokens


def _price_for(model: str, input_tokens: int, output_tokens: int) -> float:
    """Approximate cost when an API does not return a cost field."""

    known = {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
        "claude-3-5-sonnet-20241022": (3.00, 15.00),
        "claude-3-5-sonnet-latest": (3.00, 15.00),
        "claude-3-7-sonnet-latest": (3.00, 15.00),
    }
    input_price, output_price = known.get(model, (0.0, 0.0))
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(item.get("text", ""))
            for item in value
            if isinstance(item, Mapping) and item.get("type") in (None, "text")
        )
    return str(value or "")


def _usage_from_payload(
    payload: Mapping[str, Any] | None,
    *,
    provider: str,
    model: str,
    messages: Sequence[ChatMessage],
    content: str,
) -> ProviderUsage:
    usage = payload or {}
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    if input_tokens <= 0 and output_tokens <= 0:
        input_tokens, output_tokens = _estimate_tokens(messages, content)
    explicit_cost = usage.get("cost")
    try:
        cost = float(explicit_cost) if explicit_cost is not None else _price_for(model, input_tokens, output_tokens)
    except (TypeError, ValueError):
        cost = _price_for(model, input_tokens, output_tokens)
    return ProviderUsage(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=max(0.0, cost),
    )


class _HttpProvider:
    name = "generic"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 60.0,
        default_models: Sequence[str] = (),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.timeout_seconds = timeout_seconds
        self.default_models = tuple(default_models)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _response_error(self, response: httpx.Response) -> ProviderError:
        detail = "request failed"
        try:
            payload = response.json()
            error = payload.get("error") if isinstance(payload, Mapping) else None
            if isinstance(error, Mapping):
                detail = str(error.get("message") or error.get("code") or detail)
            elif isinstance(error, str):
                detail = error
            elif isinstance(payload, Mapping):
                detail = str(payload.get("message") or detail)
        except (ValueError, json.JSONDecodeError):
            detail = response.text[:200] or detail
        return ProviderError(
            f"HTTP {response.status_code}: {detail}",
            provider=self.name,
            status_code=response.status_code,
        )

    def _request_json(self, method: str, path: str, **kwargs: Any) -> Mapping[str, Any]:
        kwargs.setdefault("headers", self._headers())
        kwargs.setdefault("timeout", self.timeout_seconds)
        try:
            response = self.client.request(method, self._url(path), **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError("network request failed", provider=self.name) from exc
        if response.status_code >= 400:
            raise self._response_error(response)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("provider returned invalid JSON", provider=self.name) from exc
        if not isinstance(payload, Mapping):
            raise ProviderError("provider returned an invalid response", provider=self.name)
        return payload

    def _open_stream(self, path: str, **kwargs: Any) -> httpx.Response:
        kwargs.setdefault("headers", self._headers())
        kwargs.setdefault("timeout", self.timeout_seconds)
        try:
            stream_context = self.client.stream("POST", self._url(path), **kwargs)
            response = stream_context.__enter__()
        except httpx.HTTPError as exc:
            raise ProviderError("network request failed", provider=self.name) from exc
        if response.status_code >= 400:
            error = self._response_error(response)
            response.close()
            raise error
        return response

    def count_tokens(self, messages: Sequence[ChatMessage], model: str | None = None) -> int:
        del model
        input_tokens, _ = _estimate_tokens(messages)
        return input_tokens

    def model_list(self) -> list[ModelInfo]:
        payload = self._request_json("GET", "/models")
        raw_models = payload.get("data", payload.get("models", []))
        if not isinstance(raw_models, list):
            raise ProviderError("provider returned an invalid model list", provider=self.name)
        models = [
            ModelInfo(id=str(item.get("id")), provider=self.name)
            for item in raw_models
            if isinstance(item, Mapping) and item.get("id")
        ]
        if models:
            return models
        return [ModelInfo(id=model, provider=self.name) for model in self.default_models]

    @staticmethod
    def _iter_sse(response: httpx.Response) -> Iterator[tuple[str, str]]:
        event = "message"
        data_lines: list[str] = []
        try:
            for line in response.iter_lines():
                if line == "":
                    if data_lines:
                        yield event, "\n".join(data_lines)
                    event = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            if data_lines:
                yield event, "\n".join(data_lines)
        finally:
            response.close()


class OpenAICompatibleProvider(_HttpProvider):
    """Adapter for OpenAI and OpenAI-compatible chat-completions APIs."""

    def __init__(self, *, provider_name: str = "generic", **kwargs: Any) -> None:
        self.name = provider_name
        super().__init__(**kwargs)

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or (self.default_models[0] if self.default_models else ""),
            "messages": [dict(message) for message in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream"] = True
        return payload

    def chat(
        self,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        selected_model = model or (self.default_models[0] if self.default_models else "")
        payload = self._request_json(
            "POST",
            "/chat/completions",
            json=self._payload(messages, selected_model, temperature, max_tokens),
        )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("provider returned no choices", provider=self.name)
        first = choices[0]
        message = first.get("message", {}) if isinstance(first, Mapping) else {}
        content = _content_text(message.get("content", "")) if isinstance(message, Mapping) else ""
        return ChatResponse(
            content=content,
            usage=_usage_from_payload(
                payload.get("usage") if isinstance(payload.get("usage"), Mapping) else None,
                provider=self.name,
                model=selected_model,
                messages=messages,
                content=content,
            ),
        )

    def stream(
        self,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> Iterator[StreamChunk]:
        selected_model = model or (self.default_models[0] if self.default_models else "")
        response = self._open_stream(
            "/chat/completions",
            json=self._payload(messages, selected_model, temperature, max_tokens, stream=True),
        )
        output_parts: list[str] = []
        usage_payload: Mapping[str, Any] | None = None
        try:
            for _event, raw_data in self._iter_sse(response):
                if raw_data == "[DONE]":
                    break
                try:
                    payload = json.loads(raw_data)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(payload, Mapping) and isinstance(payload.get("usage"), Mapping):
                    usage_payload = payload["usage"]
                choices = payload.get("choices", []) if isinstance(payload, Mapping) else []
                if not isinstance(choices, list) or not choices:
                    continue
                delta = choices[0].get("delta", {}) if isinstance(choices[0], Mapping) else {}
                text = _content_text(delta.get("content", "")) if isinstance(delta, Mapping) else ""
                if text:
                    output_parts.append(text)
                    yield StreamChunk(delta=text)
        finally:
            response.close()
        input_tokens, output_tokens = _estimate_tokens(messages, "".join(output_parts))
        usage = _usage_from_payload(
            usage_payload,
            provider=self.name,
            model=selected_model,
            messages=messages,
            content="".join(output_parts),
        )
        if usage_payload is None and (input_tokens or output_tokens):
            usage = ProviderUsage(
                provider=self.name,
                model=selected_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=_price_for(selected_model, input_tokens, output_tokens),
            )
        yield StreamChunk(delta="", done=True, usage=usage)


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            provider_name="openai",
            base_url=kwargs.pop("base_url", None) or "https://api.openai.com/v1",
            default_models=kwargs.pop("default_models", ("gpt-4o-mini",)),
            **kwargs,
        )


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            provider_name="openrouter",
            base_url=kwargs.pop("base_url", None) or "https://openrouter.ai/api/v1",
            default_models=kwargs.pop("default_models", ("openai/gpt-4o-mini",)),
            **kwargs,
        )

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers.setdefault("HTTP-Referer", os.getenv("SYMBIOT_APP_URL", "http://localhost:5173"))
        headers.setdefault("X-Title", "symbiot")
        return headers


class OpenCodeAIProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            provider_name="opencode_ai",
            base_url=kwargs.pop("base_url", None) or "https://opencode.ai/zen/v1",
            default_models=kwargs.pop("default_models", ("opencode/big-pickle",)),
            **kwargs,
        )


class GenericOpenAICompatibleProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs: Any) -> None:
        base_url = kwargs.pop("base_url", None)
        if not base_url:
            raise ValueError("base_url is required for a generic OpenAI-compatible provider")
        super().__init__(provider_name="generic", base_url=base_url, **kwargs)


class AnthropicProvider(_HttpProvider):
    name = "anthropic"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            base_url=kwargs.pop("base_url", None) or "https://api.anthropic.com/v1",
            default_models=kwargs.pop(
                "default_models",
                ("claude-3-5-sonnet-latest", "claude-3-7-sonnet-latest"),
            ),
            **kwargs,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    @staticmethod
    def _anthropic_messages(messages: Sequence[ChatMessage]) -> tuple[str | None, list[dict[str, str]]]:
        system: str | None = None
        result: list[dict[str, str]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = str(message.get("content", ""))
            if role == "system":
                system = f"{system}\n{content}" if system else content
            else:
                result.append({"role": "assistant" if role == "assistant" else "user", "content": content})
        return system, result

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int | None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        system, user_messages = self._anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or 4096,
            "messages": user_messages,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        if stream:
            payload["stream"] = True
        return payload

    def chat(
        self,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        selected_model = model or self.default_models[0]
        payload = self._request_json(
            "POST",
            "/messages",
            json=self._payload(messages, selected_model, temperature, max_tokens),
        )
        content = _content_text(payload.get("content", ""))
        return ChatResponse(
            content=content,
            usage=_usage_from_payload(
                payload.get("usage") if isinstance(payload.get("usage"), Mapping) else None,
                provider=self.name,
                model=selected_model,
                messages=messages,
                content=content,
            ),
        )

    def stream(
        self,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> Iterator[StreamChunk]:
        selected_model = model or self.default_models[0]
        response = self._open_stream(
            "/messages",
            json=self._payload(messages, selected_model, temperature, max_tokens, stream=True),
        )
        output_parts: list[str] = []
        usage_payload: dict[str, Any] = {}
        try:
            for event, raw_data in self._iter_sse(response):
                try:
                    payload = json.loads(raw_data)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, Mapping):
                    continue
                if event == "content_block_delta":
                    delta = payload.get("delta", {})
                    text = str(delta.get("text", "")) if isinstance(delta, Mapping) else ""
                    if text:
                        output_parts.append(text)
                        yield StreamChunk(delta=text)
                elif event == "message_start":
                    message = payload.get("message", {})
                    if isinstance(message, Mapping) and isinstance(message.get("usage"), Mapping):
                        usage_payload.update(message["usage"])
                elif event == "message_delta":
                    usage = payload.get("usage", {})
                    if isinstance(usage, Mapping):
                        usage_payload.update(usage)
        finally:
            response.close()
        input_tokens = int(usage_payload.get("input_tokens", 0) or 0)
        output_tokens = int(usage_payload.get("output_tokens", 0) or 0)
        if input_tokens <= 0 and output_tokens <= 0:
            input_tokens, output_tokens = _estimate_tokens(messages, "".join(output_parts))
        usage = ProviderUsage(
            provider=self.name,
            model=selected_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_price_for(selected_model, input_tokens, output_tokens),
        )
        yield StreamChunk(delta="", done=True, usage=usage)


BUILTIN_PROVIDER_DEFINITIONS: dict[str, ProviderDefinition] = {
    "anthropic": ProviderDefinition(
        id="anthropic",
        kind="anthropic",
        default_model="claude-3-5-sonnet-latest",
        label="Anthropic",
    ),
    "openai": ProviderDefinition(
        id="openai",
        kind="openai",
        default_model="gpt-4o-mini",
        label="OpenAI",
    ),
    "openrouter": ProviderDefinition(
        id="openrouter",
        kind="openrouter",
        default_model="openai/gpt-4o-mini",
        label="OpenRouter",
    ),
    "opencode_ai": ProviderDefinition(
        id="opencode_ai",
        kind="opencode_ai",
        default_model="opencode/big-pickle",
        label="OpenCode AI",
    ),
}


def create_provider(
    definition: ProviderDefinition | Mapping[str, Any],
    *,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> Provider:
    if not isinstance(definition, ProviderDefinition):
        raw = dict(definition)
        raw["models"] = tuple(raw.get("models", ()))
        definition = ProviderDefinition(**raw)
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "client": client,
        "default_models": definition.models or (definition.default_model,),
    }
    if definition.base_url:
        kwargs["base_url"] = definition.base_url
    kind = definition.kind.lower().replace("-", "_")
    if kind == "anthropic":
        return AnthropicProvider(**kwargs)
    if kind == "openai":
        return OpenAIProvider(**kwargs)
    if kind == "openrouter":
        return OpenRouterProvider(**kwargs)
    if kind in {"opencode", "opencode_ai"}:
        return OpenCodeAIProvider(**kwargs)
    if kind in {"generic", "openai_compatible", "ollama", "vllm"}:
        return GenericOpenAICompatibleProvider(**kwargs)
    raise ProviderConfigurationError(
        f"unsupported provider kind '{definition.kind}'",
        provider=definition.id,
    )


def _default_model(provider: str) -> str:
    definition = BUILTIN_PROVIDER_DEFINITIONS.get(provider)
    return definition.default_model if definition else ""


def normalize_run_config(value: RunConfig | Mapping[str, Any] | None = None) -> RunConfig:
    """Accept the compact UI shape as well as the persisted Pydantic shape."""

    if isinstance(value, RunConfig):
        return value
    if value:
        raw = dict(value)
        if "primary" not in raw:
            provider = raw.pop("provider", raw.pop("model_provider", "openai"))
            model = raw.pop("model", raw.pop("model_name", "")) or _default_model(str(provider))
            raw["primary"] = {"provider": provider, "model": model}
        if "fallback_chain" in raw and "fallbacks" not in raw:
            raw["fallbacks"] = raw.pop("fallback_chain")
        return RunConfig.model_validate(raw)

    settings = Settings()
    provider = settings.model_provider
    model = settings.model_name or _default_model(provider)
    fallbacks: list[ModelSelection] = []
    for item in settings.fallback_chain.split(",") if settings.fallback_chain else []:
        if not item.strip():
            continue
        parts = item.strip().split(":", 1)
        fallback_provider = parts[0]
        fallback_model = parts[1] if len(parts) == 2 and parts[1] else _default_model(fallback_provider)
        fallbacks.append(ModelSelection(provider=fallback_provider, model=fallback_model))
    return RunConfig(
        primary=ModelSelection(provider=provider, model=model),
        fallbacks=fallbacks,
        timeout_minutes=min(settings.run_timeout_minutes, 30),
    )


class ProviderRegistry:
    """Construct providers lazily so credentials never enter persisted config."""

    def __init__(
        self,
        *,
        definitions: Mapping[str, ProviderDefinition | Mapping[str, Any]] | None = None,
        vault: Any | None = None,
        settings: Settings | None = None,
        clients: Mapping[str, httpx.Client] | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.vault = vault
        self.clients = dict(clients or {})
        merged = dict(BUILTIN_PROVIDER_DEFINITIONS)
        for provider_id, definition in (definitions or {}).items():
            if isinstance(definition, ProviderDefinition):
                merged[provider_id] = definition
            else:
                raw = dict(definition)
                raw["id"] = raw.get("id", provider_id)
                raw["models"] = tuple(raw.get("models", ()))
                merged[provider_id] = ProviderDefinition(**raw)
        self.definitions = merged

    def public_definitions(self) -> list[ProviderDefinition]:
        return list(self.definitions.values())

    def _key_for(self, definition: ProviderDefinition) -> str | None:
        env_names = {
            "anthropic": "anthropic_api_key",
            "openai": "openai_api_key",
            "openrouter": "openrouter_api_key",
            "opencode_ai": "opencode_api_key",
            "opencode": "opencode_api_key",
            "generic": "generic_api_key",
        }
        setting_name = env_names.get(definition.id, env_names.get(definition.kind))
        if setting_name:
            value = getattr(self.settings, setting_name, None)
            if value:
                return value
        if definition.id == self.settings.model_provider and self.settings.api_key:
            return self.settings.api_key
        if self.vault is not None:
            value = self.vault.get(definition.id)
            if value:
                return value
        return None

    def get(self, provider_id: str) -> Provider:
        definition = self.definitions.get(provider_id)
        if definition is None:
            raise ProviderConfigurationError(
                f"provider '{provider_id}' is not configured",
                provider=provider_id,
            )
        if not definition.enabled:
            raise ProviderConfigurationError(
                f"provider '{provider_id}' is disabled",
                provider=provider_id,
            )
        kind = definition.kind.lower().replace("-", "_")
        api_key = self._key_for(definition)
        if kind in {"anthropic", "openai", "openrouter", "opencode", "opencode_ai"} and not api_key:
            raise ProviderConfigurationError(
                f"no API key configured for provider '{provider_id}'",
                provider=provider_id,
            )
        return create_provider(
            definition,
            api_key=api_key,
            client=self.clients.get(provider_id),
        )


class ProviderRouter:
    """Retry a selected provider, then fail over to each configured fallback."""

    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        retry_policy: RetryPolicy | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self.registry = registry
        self.retry_policy = retry_policy or RetryPolicy()
        self.sleeper = sleeper
        self.random_fn = random_fn

    def _chain(self, run_config: RunConfig | Mapping[str, Any] | None) -> list[ModelSelection]:
        config = normalize_run_config(run_config)
        chain = [config.primary, *config.fallbacks]
        unique: list[ModelSelection] = []
        seen: set[tuple[str, str]] = set()
        for selection in chain:
            key = (selection.provider, selection.model)
            if key not in seen:
                unique.append(selection)
                seen.add(key)
        return unique

    def _delay(self, retry_number: int) -> float:
        base = min(
            self.retry_policy.max_delay_seconds,
            self.retry_policy.base_delay_seconds * (2**retry_number),
        )
        return base + self.random_fn() * self.retry_policy.jitter_seconds

    def _reserve(self, ledger: Any | None, provider: str) -> None:
        if ledger is not None:
            ledger.reserve_call(provider)

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        run_config: RunConfig | Mapping[str, Any] | None = None,
        ledger: Any | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        failures: list[tuple[str, str]] = []
        for selection in self._chain(run_config):
            try:
                provider = self.registry.get(selection.provider)
            except ProviderError as exc:
                failures.append((selection.provider, str(exc)))
                continue
            attempts = max(1, self.retry_policy.max_attempts)
            for attempt in range(attempts):
                self._reserve(ledger, selection.provider)
                try:
                    return provider.chat(
                        messages,
                        selection.model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except ProviderError as exc:
                    if exc.retryable and attempt + 1 < attempts:
                        self.sleeper(self._delay(attempt))
                        continue
                    failures.append((selection.provider, str(exc)))
                    break
                except Exception as exc:
                    failures.append((selection.provider, _sanitize_error(str(exc))))
                    break
        raise ProviderChainError(failures or [("provider-chain", "no providers configured")])

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        run_config: RunConfig | Mapping[str, Any] | None = None,
        ledger: Any | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> Iterator[StreamChunk]:
        failures: list[tuple[str, str]] = []
        for selection in self._chain(run_config):
            try:
                provider = self.registry.get(selection.provider)
            except ProviderError as exc:
                failures.append((selection.provider, str(exc)))
                continue
            attempts = max(1, self.retry_policy.max_attempts)
            for attempt in range(attempts):
                self._reserve(ledger, selection.provider)
                iterator: Iterator[StreamChunk] | None = None
                try:
                    iterator = iter(provider.stream(
                        messages,
                        selection.model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ))
                    first = next(iterator)
                    yield first
                    yield from iterator
                    return
                except ProviderError as exc:
                    if exc.retryable and attempt + 1 < attempts:
                        self.sleeper(self._delay(attempt))
                        continue
                    failures.append((selection.provider, str(exc)))
                    break
                except StopIteration:
                    return
                except Exception as exc:
                    failures.append((selection.provider, _sanitize_error(str(exc))))
                    break
        raise ProviderChainError(failures or [("provider-chain", "no providers configured")])

    def count_tokens(
        self,
        messages: Sequence[ChatMessage],
        *,
        run_config: RunConfig | Mapping[str, Any] | None = None,
    ) -> int:
        selection = self._chain(run_config)[0]
        provider = self.registry.get(selection.provider)
        return provider.count_tokens(messages, selection.model)

    def model_list(self, provider_id: str) -> list[ModelInfo]:
        return self.registry.get(provider_id).model_list()
