"""Persist provider metadata separately from encrypted provider keys."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from symbiot.providers import (
    BUILTIN_PROVIDER_DEFINITIONS,
    ProviderDefinition,
    ProviderRegistry,
    create_provider,
    mask_api_key,
    normalize_run_config,
    validate_api_key,
)
from symbiot.schemas import ModelSelection, RunConfig
from symbiot.vault import LocalKeyVault


class ProviderStoreError(RuntimeError):
    pass


def _validate_base_url(base_url: str | None) -> None:
    if not base_url:
        return
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderStoreError("base URL must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderStoreError("base URL must not contain credentials, query parameters, or fragments")


class ProviderStore:
    """A metadata-only JSON store; secrets are always written to ``LocalKeyVault``."""

    def __init__(self, path: str | Path | None = None) -> None:
        config_dir = Path(os.getenv("SYMBIOT_CONFIG_DIR", Path.home() / ".symbiot"))
        self.path = Path(path or config_dir / "providers.json")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"providers": {}, "routing": {}}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderStoreError("provider configuration is unreadable") from exc
        if not isinstance(data, dict):
            raise ProviderStoreError("provider configuration has an invalid format")
        data.setdefault("providers", {})
        data.setdefault("routing", {})
        if not isinstance(data["providers"], dict) or not isinstance(data["routing"], dict):
            raise ProviderStoreError("provider configuration has an invalid format")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def definitions(self) -> dict[str, ProviderDefinition]:
        data = self._read()
        result: dict[str, ProviderDefinition] = {}
        for provider_id, raw in data["providers"].items():
            if not isinstance(raw, dict):
                raise ProviderStoreError("provider configuration has an invalid provider entry")
            clean = dict(raw)
            clean["id"] = provider_id
            clean["models"] = tuple(clean.get("models", ()))
            try:
                result[provider_id] = ProviderDefinition(**clean)
            except (TypeError, ValueError) as exc:
                raise ProviderStoreError(f"provider '{provider_id}' is invalid") from exc
        return result

    def upsert(self, definition: ProviderDefinition) -> ProviderDefinition:
        data = self._read()
        data["providers"][definition.id] = {
            "kind": definition.kind,
            "default_model": definition.default_model,
            "base_url": definition.base_url,
            "label": definition.label,
            "enabled": definition.enabled,
            "models": list(definition.models),
            "is_default": definition.is_default,
            "fallback_order": definition.fallback_order,
        }
        self._write(data)
        return definition

    def remove(self, provider_id: str) -> None:
        data = self._read()
        data["providers"].pop(provider_id, None)
        fallbacks = data["routing"].get("fallbacks", [])
        data["routing"]["fallbacks"] = [item for item in fallbacks if item.get("provider") != provider_id]
        if data["routing"].get("primary", {}).get("provider") == provider_id:
            data["routing"].pop("primary", None)
        self._write(data)

    def routing(self) -> RunConfig | None:
        routing = self._read().get("routing", {})
        if not routing.get("primary"):
            return None
        try:
            return normalize_run_config(routing)
        except ValueError as exc:
            raise ProviderStoreError("provider fallback routing is invalid") from exc

    def set_routing(
        self,
        primary: ModelSelection,
        fallbacks: list[ModelSelection],
    ) -> RunConfig:
        data = self._read()
        config = RunConfig(primary=primary, fallbacks=fallbacks)
        data["routing"] = config.model_dump()
        self._write(data)
        return config


class ProviderManager:
    def __init__(
        self,
        *,
        store: ProviderStore | None = None,
        vault: LocalKeyVault | None = None,
    ) -> None:
        self.store = store or ProviderStore()
        self.vault = vault or LocalKeyVault()

    def registry(self) -> ProviderRegistry:
        return ProviderRegistry(definitions=self.store.definitions(), vault=self.vault)

    def list_public(self) -> list[dict[str, Any]]:
        registry = self.registry()
        routing = self.store.routing()
        fallback_keys = {(item.provider, item.model) for item in routing.fallbacks} if routing else set()
        results: list[dict[str, Any]] = []
        for definition in registry.public_definitions():
            key = registry._key_for(definition)
            results.append(
                {
                    "id": definition.id,
                    "kind": definition.kind,
                    "label": definition.label or definition.id,
                    "default_model": definition.default_model,
                    "base_url": definition.base_url,
                    "enabled": definition.enabled,
                    "models": list(definition.models),
                    "has_key": bool(key),
                    "key_masked": mask_api_key(key),
                    "is_default": bool(routing and routing.primary.provider == definition.id)
                    or definition.is_default,
                    "fallback": any(provider == definition.id for provider, _ in fallback_keys),
                }
            )
        return results

    def save(
        self,
        *,
        provider_id: str,
        kind: str,
        default_model: str,
        base_url: str | None = None,
        label: str | None = None,
        models: list[str] | None = None,
        enabled: bool = True,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        _validate_base_url(base_url)
        if api_key is not None:
            try:
                validate_api_key(kind, api_key)
            except ValueError as exc:
                raise ProviderStoreError(str(exc)) from exc
            self.vault.set(provider_id, api_key)
        definition = ProviderDefinition(
            id=provider_id,
            kind=kind,
            default_model=default_model,
            base_url=base_url,
            label=label,
            models=tuple(models or ()),
            enabled=enabled,
        )
        self.store.upsert(definition)
        return next(item for item in self.list_public() if item["id"] == provider_id)

    def test_connection(self, provider_id: str, model: str | None = None) -> dict[str, Any]:
        registry = self.registry()
        definition = registry.definitions.get(provider_id)
        if definition is None:
            raise ProviderStoreError(f"provider '{provider_id}' is not configured")
        provider = registry.get(provider_id)
        models = provider.model_list()
        selected = model or definition.default_model
        return {
            "ok": True,
            "provider": provider_id,
            "model": selected,
            "models": [
                {
                    "id": info.id,
                    "provider": info.provider,
                    "context_window": info.context_window,
                    "input_cost_per_million": info.input_cost_per_million,
                    "output_cost_per_million": info.output_cost_per_million,
                }
                for info in models
            ],
        }

    def set_routing(self, primary: ModelSelection, fallbacks: list[ModelSelection]) -> RunConfig:
        known = set(self.registry().definitions)
        selections = [primary, *fallbacks]
        if any(selection.provider not in known for selection in selections):
            raise ProviderStoreError("routing references an unknown provider")
        return self.store.set_routing(primary, fallbacks)
