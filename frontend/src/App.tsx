import { useCallback, useEffect, useMemo, useState } from "react";
import { sidecar } from "./api/sidecar";
import { CommandPalette, type PaletteAction } from "./components/CommandPalette";
import { EscalationCenter } from "./components/EscalationCenter";
import { HistoryView } from "./components/HistoryView";
import { MissionConsole } from "./components/MissionConsole";
import { ProfileView } from "./components/ProfileView";
import { ProvidersView } from "./components/ProvidersView";
import { useLangGraphStream } from "./hooks/useLangGraphStream";
import { SymbioteCrest } from "./components/SymbioteCrest";
import { budgetFromState } from "./lib/mission";
import type { RunConfig, RunRecord, ScreenId } from "./types";

const DEFAULT_SPEC = `## META
name: todo-cli | stack: python 3.12 | runtime: cli | entrypoint: todo.py | smoke_command: list

## OBJECTIVE
CLI that adds and lists todos stored in todos.json.

## END_CRITERIA
- \`python todo.py add "x"\` writes valid json
- \`python todo.py list\` prints stored todos
- pytest suite passes

## MILESTONES
- {id: m1, title: add command, acceptance_criteria: ["add writes valid json"], max_attempts: 3}
- {id: m2, title: list command, acceptance_criteria: ["list prints stored todos"], max_attempts: 3}

## BUDGET
token_cap: 500000
llm_call_cap: 50

## OUT_OF_SCOPE
no database, no web UI`;

const DEFAULT_RUN_CONFIG: RunConfig = {
  primary: { provider: "openai", model: "gpt-4o-mini" },
  fallbacks: [],
  timeout_minutes: 30,
};

const NAV_ITEMS: { id: ScreenId; label: string; icon: string; shortcut: string }[] = [
  { id: "console", label: "Run console", icon: "◈", shortcut: "G" },
  { id: "escalation", label: "Escalation center", icon: "!", shortcut: "E" },
  { id: "providers", label: "Providers", icon: "⬡", shortcut: "P" },
  { id: "history", label: "Run history", icon: "▤", shortcut: "H" },
  { id: "profile", label: "Profile", icon: "◉", shortcut: "O" },
];

function statusLabel(status: string): string {
  return status === "interrupted" ? "human action" : status;
}

export default function App() {
  const stream = useLangGraphStream();
  const [screen, setScreen] = useState<ScreenId>("console");
  const [spec, setSpec] = useState(DEFAULT_SPEC);
  const [runConfig, setRunConfig] = useState<RunConfig>(DEFAULT_RUN_CONFIG);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const navigate = useCallback((next: ScreenId) => setScreen(next), []);
  const budget = useMemo(() => budgetFromState(stream.state), [stream.state]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
      if (event.key === "Escape" && paletteOpen) setPaletteOpen(false);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [paletteOpen]);

  const launch = useCallback(() => {
    void stream.startRun(spec, undefined, runConfig);
  }, [runConfig, spec, stream]);

  const rerun = useCallback(async (record: RunRecord) => {
    let specText = record.spec;
    if (!specText) {
      try {
        specText = await sidecar.getSpec(record.projectName);
      } catch {
        specText = "";
      }
    }
    const nextSpec = specText || DEFAULT_SPEC;
    setSpec(nextSpec);
    setRunConfig(record.runConfig ?? DEFAULT_RUN_CONFIG);
    setScreen("console");
    void stream.startRun(nextSpec, undefined, record.runConfig);
  }, [stream]);

  const paletteActions = useMemo<PaletteAction[]>(() => [
    { id: "launch", label: "Launch mission", detail: "Run the current PROJECT.md through the factory", shortcut: "⌘↵", run: launch },
    ...NAV_ITEMS.map(item => ({ id: item.id, label: `Open ${item.label}`, detail: "Navigate control room", shortcut: item.shortcut, run: () => navigate(item.id) })),
    { id: "reset", label: "Reset live console", detail: "Clear the active mission view", run: stream.reset },
  ], [launch, navigate, stream.reset]);

  const displayedScreen: ScreenId = stream.interruptPayload ? "escalation" : screen;

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand-lockup"><span className="brand-mark"><SymbioteCrest /></span><span><strong>symbiot</strong><small>hive-mind mission control</small></span></div>
        <div className="sidebar-label">Command deck</div>
        <nav className="main-nav" aria-label="Main navigation">
          {NAV_ITEMS.map(item => <button key={item.id} className={`nav-item ${screen === item.id ? "active" : ""}`} onClick={() => navigate(item.id)}><span className="nav-icon">{item.icon}</span><span>{item.label}</span>{item.id === "escalation" && stream.interruptPayload && <i className="nav-alert" />}</button>)}
        </nav>
      </aside>
      <div className="app-main">
        <header className="topbar"><div className="breadcrumb"><span>SYMBIOT /</span><strong>{NAV_ITEMS.find(item => item.id === displayedScreen)?.label}</strong></div><div className="topbar-right"><span className={`top-status top-${stream.status}`}><i /> {statusLabel(stream.status)}</span>{stream.threadId && <span className="thread-chip">{stream.threadId.slice(0, 10)}</span>}<button className="top-avatar" onClick={() => navigate("profile")} aria-label="AB">AB</button></div></header>
        <main className="content-wrap">
          {displayedScreen === "console" && <MissionConsole spec={spec} onSpecChange={setSpec} runConfig={runConfig} onRunConfigChange={setRunConfig} onRun={launch} onOpenProviders={() => navigate("providers")} status={stream.status} activeNode={stream.activeNode} completedNodes={stream.completedNodes} liveStatus={stream.liveStatus} budget={budget} activity={stream.activity} terminal={stream.terminal} fileTree={stream.fileTree} connectionError={stream.connectionError} />}
          {displayedScreen === "escalation" && <EscalationCenter payload={stream.interruptPayload} onAction={stream.resumeInterrupt} />}
          {displayedScreen === "providers" && <ProvidersView runConfig={runConfig} onRunConfigChange={setRunConfig} />}
          {displayedScreen === "history" && <HistoryView records={stream.history} onRerun={rerun} />}
          {displayedScreen === "profile" && <ProfileView />}
        </main>
      </div>
      <CommandPalette open={paletteOpen} actions={paletteActions} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
