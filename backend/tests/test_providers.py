import json
import os

import httpx
import pytest
from cryptography.fernet import Fernet

from symbiot.guards import BudgetExhaustedError, BudgetLedger
from symbiot.providers import (
    AnthropicProvider,
    ChatResponse,
    GenericOpenAICompatibleProvider,
    ModelInfo,
    OpenAIProvider,
    OpenCodeAIProvider,
    OpenRouterProvider,
    Provider,
    ProviderChainError,
    ProviderError,
    ProviderRegistry,
    ProviderRouter,
    ProviderUsage,
    RetryPolicy,
    StreamChunk,
    create_provider,
    validate_api_key,
)
from symbiot.provider_store import ProviderManager, ProviderStore, ProviderStoreError
from symbiot.schemas import Budget, ModelSelection
from symbiot.vault import LocalKeyVault


MESSAGES = [
    {"role": "system", "content": "Return JSON."},
    {"role": "user", "content": "Hello"},
]


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_adapter_chat_and_model_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test-key"
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "gpt-test"}]})
        body = json.loads(request.content)
        assert body["model"] == "gpt-test"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{\"ok\":true}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    provider = OpenAIProvider(
        api_key="sk-test-key",
        base_url="https://mock.local/v1",
        default_models=("gpt-test",),
        client=client_for(handler),
    )
    assert isinstance(provider, Provider)
    result = provider.chat(MESSAGES, "gpt-test")
    assert result.content == '{"ok":true}'
    assert result.usage.total_tokens == 14
    assert provider.model_list() == [ModelInfo(id="gpt-test", provider="openai")]


def test_anthropic_adapter_translates_system_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "sk-ant-test-key"
        body = json.loads(request.content)
        assert body["system"] == "Return JSON."
        assert body["messages"] == [{"role": "user", "content": "Hello"}]
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "{}"}],
                "usage": {"input_tokens": 7, "output_tokens": 2},
            },
        )

    provider = AnthropicProvider(
        api_key="sk-ant-test-key",
        base_url="https://mock.local/v1",
        client=client_for(handler),
    )
    result = provider.chat(MESSAGES, "claude-test")
    assert result.content == "{}"
    assert result.usage.total_tokens == 9


def test_compatible_adapters_have_distinct_provider_names() -> None:
    definitions = {
        "router": {"id": "router", "kind": "openrouter", "default_model": "router-test"},
        "code": {"id": "code", "kind": "opencode_ai", "default_model": "code-test"},
        "local": {
            "id": "local",
            "kind": "generic",
            "default_model": "local-test",
            "base_url": "http://localhost:11434/v1",
        },
    }
    assert create_provider(definitions["router"], api_key="sk-or-test-key").name == "openrouter"
    assert create_provider(definitions["code"], api_key="sk-test-key").name == "opencode_ai"
    assert isinstance(create_provider(definitions["local"]), GenericOpenAICompatibleProvider)


def test_openai_stream_emits_deltas_and_usage() -> None:
    body = (
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b'data: {"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    provider = OpenAIProvider(
        api_key="sk-test-key",
        base_url="https://mock.local/v1",
        default_models=("gpt-test",),
        client=client_for(handler),
    )
    chunks = list(provider.stream(MESSAGES, "gpt-test"))
    assert "".join(chunk.delta for chunk in chunks) == "hello"
    assert chunks[-1].done is True
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 5


class FakeProvider:
    name = "fake"

    def __init__(self, failures: list[ProviderError] | None = None) -> None:
        self.failures = list(failures or [])
        self.calls = 0

    def chat(self, messages, model=None, *, temperature=0.0, max_tokens=None) -> ChatResponse:
        del messages, model, temperature, max_tokens
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return ChatResponse(
            content="{}",
            usage=ProviderUsage(provider=self.name, model="fake", input_tokens=2, output_tokens=3),
        )

    def stream(self, messages, model=None, *, temperature=0.0, max_tokens=None):
        del messages, model, temperature, max_tokens
        yield StreamChunk(delta="{}")
        yield StreamChunk(delta="", done=True, usage=ProviderUsage(provider=self.name, model="fake", input_tokens=2, output_tokens=1))

    def count_tokens(self, messages, model=None):
        del messages, model
        return 2

    def model_list(self):
        return [ModelInfo(id="fake", provider=self.name)]


class FakeRegistry(ProviderRegistry):
    def __init__(self, providers):
        self.fake_providers = providers

    def get(self, provider_id):
        return self.fake_providers[provider_id]


def test_router_retries_429_and_falls_back_after_primary_exhaustion() -> None:
    primary = FakeProvider(
        [
            ProviderError("rate limited", provider="primary", status_code=429),
            ProviderError("rate limited", provider="primary", status_code=429),
            ProviderError("server", provider="primary", status_code=503),
        ]
    )
    secondary = FakeProvider()
    router = ProviderRouter(
        FakeRegistry({"primary": primary, "secondary": secondary}),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0, jitter_seconds=0),
        sleeper=lambda _delay: None,
    )
    ledger = BudgetLedger({"budget": Budget(token_cap=100, llm_call_cap=10)})
    response = router.chat(
        MESSAGES,
        run_config={
            "primary": {"provider": "primary", "model": "one"},
            "fallbacks": [{"provider": "secondary", "model": "two"}],
        },
        ledger=ledger,
    )
    assert response.content == "{}"
    assert primary.calls == 3
    assert secondary.calls == 1
    assert ledger.budget.llm_calls == 4
    assert ledger.budget.calls_by_provider == {"primary": 3, "secondary": 1}


def test_router_stops_before_call_cap() -> None:
    primary = FakeProvider([ProviderError("busy", provider="primary", status_code=429)])
    router = ProviderRouter(
        FakeRegistry({"primary": primary}),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0, jitter_seconds=0),
        sleeper=lambda _delay: None,
    )
    ledger = BudgetLedger({"budget": Budget(token_cap=100, llm_call_cap=1)})
    with pytest.raises(BudgetExhaustedError):
        router.chat(
            MESSAGES,
            run_config={"primary": {"provider": "primary", "model": "one"}},
            ledger=ledger,
        )
    assert primary.calls == 1
    assert ledger.budget.llm_calls == 1


def test_router_reports_safe_chain_error() -> None:
    router = ProviderRouter(FakeRegistry({"primary": FakeProvider([ProviderError("bad", provider="primary")])}))
    with pytest.raises(ProviderChainError) as error:
        router.chat(
            MESSAGES,
            run_config={"primary": {"provider": "primary", "model": "one"}},
        )
    assert "primary" in str(error.value)
    assert "sk-" not in str(error.value)


def test_vault_encrypts_keys_and_validates_shapes(tmp_path) -> None:
    key = Fernet.generate_key()
    vault = LocalKeyVault(tmp_path / "vault.enc", master_key=key, key_path=tmp_path / "master.key")
    validate_api_key("openai", "sk-test-key")
    validate_api_key("anthropic", "sk-ant-test-key")
    with pytest.raises(ValueError):
        validate_api_key("openrouter", "not-a-router-key")
    vault.set("openai", "sk-test-key")
    assert vault.get("openai") == "sk-test-key"
    assert b"sk-test-key" not in (tmp_path / "vault.enc").read_bytes()


def test_provider_manager_separates_metadata_from_keys(tmp_path) -> None:
    vault = LocalKeyVault(
        tmp_path / "vault.enc",
        master_key=Fernet.generate_key(),
        key_path=tmp_path / "master.key",
    )
    manager = ProviderManager(
        store=ProviderStore(tmp_path / "providers.json"),
        vault=vault,
    )
    saved = manager.save(
        provider_id="mock-openai",
        kind="openai",
        default_model="gpt-test",
        base_url="https://mock.local/v1",
        api_key="sk-test-key",
    )
    metadata = (tmp_path / "providers.json").read_text()
    assert "sk-test-key" not in metadata
    assert saved["key_masked"] == "sk-...-key"
    assert saved["has_key"] is True
    manager.set_routing(
        ModelSelection(provider="mock-openai", model="gpt-test"),
        [],
    )
    assert manager.store.routing().primary.provider == "mock-openai"


def test_provider_manager_rejects_credentials_in_endpoint_urls(tmp_path) -> None:
    manager = ProviderManager(
        store=ProviderStore(tmp_path / "providers.json"),
        vault=LocalKeyVault(tmp_path / "vault.enc", master_key=Fernet.generate_key()),
    )
    with pytest.raises(ProviderStoreError, match="base URL"):
        manager.save(
            provider_id="unsafe-url",
            kind="generic",
            default_model="local",
            base_url="https://example.invalid/v1?api_key=secret",
        )


@pytest.mark.skipif(
    os.getenv("SYMBIOT_REAL_PROVIDER_TEST") != "1",
    reason="set SYMBIOT_REAL_PROVIDER_TEST=1 to run the gated real-provider check",
)
def test_real_provider_connection_is_explicitly_gated() -> None:
    provider_name = os.getenv("SYMBIOT_REAL_PROVIDER", "openai")
    model = os.getenv("SYMBIOT_REAL_MODEL", "gpt-4o-mini")
    registry = ProviderRegistry()
    response = ProviderRouter(registry).chat(
        [{"role": "user", "content": "Reply with the word ok."}],
        run_config={"primary": {"provider": provider_name, "model": model}},
    )
    assert response.content
