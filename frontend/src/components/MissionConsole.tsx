import { useMemo } from "react";
import { PipelineRail } from "./PipelineRail";
import { TerminalPanel } from "./TerminalPanel";
import { budgetPercent, missionName } from "../lib/mission";
import type {
  ActivityEntry,
  BudgetInfo,
  FileTreeEntry,
  NodeResult,
  RunConfig,
  RunStatus,
  TerminalEntry,
} from "../types";

interface MissionConsoleProps {
  spec: string;
  onSpecChange: (spec: string) => void;
  runConfig: RunConfig;
  onRunConfigChange: (config: RunConfig) => void;
  onRun: () => void;
  onOpenProviders: () => void;
  status: RunStatus;
  activeNode: string | null;
  completedNodes: Record<string, NodeResult>;
  liveStatus: Record<string, string>;
  budget: BudgetInfo | null;
  activity: ActivityEntry[];
  terminal: TerminalEntry[];
  fileTree: FileTreeEntry[];
  connectionError: boolean;
}

function BudgetMeter({ budget }: { budget: BudgetInfo | null }) {
  const tokenPct = budget ? budgetPercent(budget.tokens_used, budget.token_cap) : 0;
  const callPct = budget ? budgetPercent(budget.llm_calls, budget.llm_call_cap) : 0;
  const costPct = budget?.cost_cap_usd ? budgetPercent(budget.cost_usd, budget.cost_cap_usd) : 0;
  const tone = tokenPct > 90 || callPct > 90 || costPct > 90 ? "danger" : tokenPct > 70 || callPct > 70 || costPct > 70 ? "warning" : "";
  return (
    <section className="panel budget-panel" aria-labelledby="budget-title">
      <div className="panel-heading"><div><span className="eyebrow">Guardrails</span><h2 id="budget-title">Mission burn</h2></div><span className={`budget-tone ${tone}`}>{tone === "danger" ? "near cap" : tone === "warning" ? "watch" : "within limits"}</span></div>
      <div className="burn-row"><span>tokens</span><strong>{budget ? budget.tokens_used.toLocaleString() : "--"}<small> / {budget?.token_cap.toLocaleString() ?? "--"}</small></strong></div>
      <div className={`burn-bar ${tone}`}><span style={{ width: `${tokenPct}%` }} /></div>
      <div className="burn-stats"><span><b>{budget?.llm_calls ?? "--"}</b> calls / {budget?.llm_call_cap ?? "--"}</span><span><b>{budget ? `$${budget.cost_usd.toFixed(4)}` : "--"}</b>{budget?.cost_cap_usd ? ` / $${budget.cost_cap_usd.toFixed(2)}` : " cost"}</span></div>
    </section>
  );
}

function ActivityPanel({ activity }: { activity: ActivityEntry[] }) {
  const recent = useMemo(() => activity.slice(-8), [activity]);
  return (
    <section className="panel activity-panel" aria-labelledby="activity-title">
      <div className="panel-heading"><div><span className="eyebrow">Event stream</span><h2 id="activity-title">Agent activity</h2></div></div>
      <div className="activity-list">
        {recent.length === 0 && <div className="empty-inline">Agents are standing by.</div>}
        {recent.map((entry, index) => <div className="activity-row" key={`${entry.ts}-${index}`}><span className={`activity-dot activity-${entry.kind ?? "info"}`} /><b>{entry.agent}</b><span>{entry.msg}</span></div>)}
      </div>
    </section>
  );
}

export function MissionConsole(props: MissionConsoleProps) {
  const isRunning = props.status === "running";
  const name = missionName(props.spec);
  return (
    <section className="screen console-screen" aria-labelledby="console-title">
      <div className="mission-intro">
        <div><span className="eyebrow">Run console / live factory</span><h1 id="console-title">Build something that survives contact.</h1><p>Drop a PROJECT.md into the factory. Watch every agent earn its next state.</p></div>
        <div className="mission-actions"><span className="mission-name"><i /> {name}</span><button className="button button-primary button-run" disabled={isRunning} onClick={props.onRun}>{isRunning ? "Factory running" : "Launch mission"}<kbd>{isRunning ? "live" : "⌘↵"}</kbd></button></div>
      </div>
      {props.connectionError && <div className="notice notice-danger">Run service unreachable. Start the backend stream and retry.</div>}

      <div className="console-grid">
        <div className="console-main">
          <section className="panel spec-panel">
            <div className="panel-heading"><div><span className="eyebrow">Mission brief</span><h2>PROJECT.md</h2></div><span className="muted-label">editable before launch</span></div>
            <textarea id="mission-spec" name="mission-spec" aria-label="PROJECT.md mission specification" spellCheck={false} value={props.spec} onChange={event => props.onSpecChange(event.target.value)} />
            <div className="spec-footer"><span><i className="status-light" /> spec loaded</span><span>{props.spec.split("\n").length} lines · {props.spec.length.toLocaleString()} chars</span></div>
          </section>
          <PipelineRail activeNode={props.activeNode} completedNodes={props.completedNodes} liveStatus={props.liveStatus} runStatus={props.status} />
          <TerminalPanel entries={props.terminal} />
        </div>
        <aside className="console-side">
          <section className="panel route-panel"><div className="panel-heading"><div><span className="eyebrow">Route selection</span><h2>Model command</h2></div><button className="text-button" onClick={props.onOpenProviders}>Manage</button></div>
            <label htmlFor="route-provider">Primary surface<select id="route-provider" value={props.runConfig.primary.provider} onChange={event => props.onRunConfigChange({ ...props.runConfig, primary: { ...props.runConfig.primary, provider: event.target.value } })}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="openrouter">OpenRouter</option><option value="opencode_ai">OpenCode AI</option><option value="ollama">Ollama / local</option></select></label>
            <label htmlFor="route-model">Model<input id="route-model" value={props.runConfig.primary.model} onChange={event => props.onRunConfigChange({ ...props.runConfig, primary: { ...props.runConfig.primary, model: event.target.value } })} /></label>
            <div className="route-fallback"><span>fallback chain</span><strong>{props.runConfig.fallbacks.length ? props.runConfig.fallbacks.map(item => item.provider).join("  →  ") : "none configured"}</strong></div>
          </section>
          <BudgetMeter budget={props.budget} />
          <ActivityPanel activity={props.activity} />
          <section className="panel workspace-panel"><div className="panel-heading"><div><span className="eyebrow">Sandbox workspace</span><h2>Artifact surface</h2></div><span className="count-badge">{props.fileTree.length}</span></div><div className="workspace-summary"><strong>{props.fileTree.filter(file => file.status === "created").length}</strong><span>new files</span><strong>{props.fileTree.filter(file => file.status === "modified").length}</strong><span>modified</span></div><div className="workspace-path">All generated code executes inside the Docker runner.</div></section>
        </aside>
      </div>
    </section>
  );
}
