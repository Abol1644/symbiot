import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { sidecar } from "../api/sidecar";
import type { ModelSelection, ProviderInfo, RunConfig } from "../types";

interface ProvidersViewProps {
  runConfig: RunConfig;
  onRunConfigChange: (config: RunConfig) => void;
}

const EMPTY_FORM = {
  id: "",
  kind: "openai",
  default_model: "gpt-4o-mini",
  base_url: "",
  label: "",
  api_key: "",
};

export function ProvidersView({ runConfig, onRunConfigChange }: ProvidersViewProps) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [fallbackIds, setFallbackIds] = useState<string[]>(runConfig.fallbacks.map(item => item.provider));
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [testing, setTesting] = useState<string | null>(null);

  const loadProviders = useCallback(async () => {
    setLoading(true);
    try {
      setProviders(await sidecar.listProviders());
      setMessage("");
    } catch {
      setMessage("Provider service unavailable. Start the local sidecar to manage connections.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadProviders(), 0);
    return () => window.clearTimeout(timer);
  }, [loadProviders]);

  const selectPrimary = (provider: ProviderInfo) => {
    onRunConfigChange({
      ...runConfig,
      primary: { provider: provider.id, model: provider.default_model },
    });
  };

  const toggleFallback = (provider: ProviderInfo) => {
    const nextIds = fallbackIds.includes(provider.id)
      ? fallbackIds.filter(id => id !== provider.id)
      : [...fallbackIds, provider.id];
    setFallbackIds(nextIds);
    onRunConfigChange({
      ...runConfig,
      fallbacks: nextIds
        .filter(id => id !== runConfig.primary.provider)
        .map(id => {
          const item = providers.find(candidate => candidate.id === id);
          return { provider: id, model: item?.default_model ?? "" };
        }),
    });
  };

  const saveProvider = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage("");
    try {
      const desktop = "__TAURI_INTERNALS__" in window;
      const key = form.api_key || undefined;
      if (desktop && key) {
        await invoke("set_provider_key", { provider: form.id, apiKey: key });
      }
      await sidecar.saveProvider({
        ...form,
        base_url: form.base_url || null,
        label: form.label || undefined,
        api_key: desktop ? undefined : key,
      });
      setForm(EMPTY_FORM);
      setMessage(desktop ? "Provider saved in the OS credential vault." : "Provider saved. The key is encrypted locally and is never returned.");
      await loadProviders();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Provider could not be saved.");
    }
  };

  const testProvider = async (provider: ProviderInfo) => {
    setTesting(provider.id);
    setMessage("");
    try {
      const result = await sidecar.testProvider(provider.id, provider.default_model);
      setMessage(`${provider.label} connected. ${result.models.length} model${result.models.length === 1 ? "" : "s"} available.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Connection test failed.");
    } finally {
      setTesting(null);
    }
  };

  const saveRouting = async () => {
    const primary: ModelSelection = runConfig.primary;
    try {
      const config = await sidecar.setProviderRouting(primary, runConfig.fallbacks);
      onRunConfigChange(config);
      setMessage("Default route saved.");
    } catch {
      setMessage("Default route could not be saved.");
    }
  };

  return (
    <section className="screen providers-screen" aria-labelledby="providers-title">
      <div className="screen-heading">
        <div><span className="eyebrow">Control plane / credentials</span><h1 id="providers-title">Providers</h1><p>Connect model surfaces once. Run configs carry only provider IDs and model names.</p></div>
        <button className="button button-primary" onClick={saveRouting}>Save default route</button>
      </div>

      {message && <div className="notice" role="status">{message}</div>}

      <div className="providers-layout">
        <div className="provider-list panel">
          <div className="panel-heading"><div><span className="eyebrow">Available surfaces</span><h2>Connection roster</h2></div><span className="count-badge">{providers.length}</span></div>
          {loading ? <div className="loading-row">Loading provider roster...</div> : providers.map(provider => (
            <article className={`provider-card ${provider.id === runConfig.primary.provider ? "provider-primary" : ""}`} key={provider.id}>
              <div className="provider-card-top">
                <div className="provider-orb">{provider.label.slice(0, 1).toUpperCase()}</div>
                <div className="provider-title"><strong>{provider.label}</strong><span>{provider.kind} · {provider.default_model}</span></div>
                <span className={`connection-state ${provider.has_key ? "connected" : "unconfigured"}`}><i />{provider.has_key ? "connected" : "no key"}</span>
              </div>
              <div className="provider-card-meta">
                <span>{provider.key_masked ? `key ${provider.key_masked}` : "credential not configured"}</span>
                <span>{provider.base_url || "managed endpoint"}</span>
              </div>
              <div className="provider-card-actions">
                <button className="button button-small" onClick={() => selectPrimary(provider)}>Use for next run</button>
                <label className="check-label"><input type="checkbox" checked={fallbackIds.includes(provider.id)} onChange={() => toggleFallback(provider)} /> fallback</label>
                <button className="text-button" disabled={testing === provider.id} onClick={() => void testProvider(provider)}>{testing === provider.id ? "Testing..." : "Test connection"}</button>
              </div>
            </article>
          ))}
        </div>

        <form className="panel provider-form" onSubmit={saveProvider}>
          <div className="panel-heading"><div><span className="eyebrow">Add surface</span><h2>Provider endpoint</h2></div></div>
          <label htmlFor="provider-id">Identifier<input id="provider-id" name="provider-id" required value={form.id} placeholder="team-openai" onChange={event => setForm({ ...form, id: event.target.value })} /></label>
          <label htmlFor="provider-kind">Adapter<select id="provider-kind" name="provider-kind" value={form.kind} onChange={event => setForm({ ...form, kind: event.target.value })}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="openrouter">OpenRouter</option><option value="opencode_ai">OpenCode AI</option><option value="generic">OpenAI-compatible / Ollama / vLLM</option></select></label>
          <label htmlFor="provider-model">Default model<input id="provider-model" name="provider-model" required value={form.default_model} placeholder="model-id" onChange={event => setForm({ ...form, default_model: event.target.value })} /></label>
          <label htmlFor="provider-base-url">Base URL <span className="label-hint">optional for managed adapters</span><input id="provider-base-url" name="provider-base-url" value={form.base_url} placeholder="https://host/v1" onChange={event => setForm({ ...form, base_url: event.target.value })} /></label>
          <label htmlFor="provider-api-key">API key <span className="label-hint">write-only</span><input id="provider-api-key" name="provider-api-key" type="password" autoComplete="new-password" value={form.api_key} placeholder="never displayed after save" onChange={event => setForm({ ...form, api_key: event.target.value })} /></label>
          <button className="button button-primary" type="submit">Encrypt and add provider</button>
          <p className="form-footnote">Keys are validated on save, encrypted in the local vault, and omitted from run state, logs, and this UI after submission.</p>
        </form>
      </div>
    </section>
  );
}
