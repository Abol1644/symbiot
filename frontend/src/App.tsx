import { useState, useMemo, useCallback } from "react";
import { useLangGraphStream } from "./hooks/useLangGraphStream";
import { GraphCanvas } from "./components/GraphCanvas";
import { StateInspector } from "./components/StateInspector";
import { FileTree } from "./components/FileTree";
import { GitPanel } from "./components/GitPanel";
import { AgentActivity } from "./components/AgentActivity";
import { LogStream } from "./components/LogStream";
import { ControlPanel } from "./components/ControlPanel";
import { InterruptModal } from "./components/InterruptModal";
import { TokenPanel } from "./components/TokenPanel";
import type { BudgetInfo, TabId } from "./types";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "files", label: "Files" },
  { id: "git", label: "Git" },
  { id: "logs", label: "Logs" },
];

export default function App() {
  const {
    status,
    activeNode,
    completedNodes,
    state,
    logs,
    interruptPayload,
    threadId,
    connectionError,
    activity,
    liveStatus,
    tokensByAgent,
    fileTree,
    startRun,
    resumeInterrupt,
    reset,
  } = useLangGraphStream();

  const [tab, setTab] = useState<TabId>("overview");

  const budget = useMemo((): BudgetInfo | null => {
    if (!state?.budget) return null;
    const b = state.budget as { tokens_used?: number; token_cap?: number; llm_calls?: number; llm_call_cap?: number };
    return {
      tokens_used: b.tokens_used ?? 0,
      token_cap: b.token_cap ?? 0,
      llm_calls: b.llm_calls ?? 0,
      llm_call_cap: b.llm_call_cap ?? 0,
    };
  }, [state]);

  const workspaceName = useMemo(() => {
    if (!state?.workspace) return null;
    const ws = state.workspace as string;
    return ws.split("/").pop() || null;
  }, [state]);

  const changedCount = useMemo(() => {
    return fileTree.filter(f => f.status === "created" || f.status === "modified").length;
  }, [fileTree]);

  const refreshFileTree = useCallback(() => {
    // fileTree updates come from streaming state updates
  }, []);

  return (
    <div className="app-layout">
      <ControlPanel
        status={status}
        threadId={threadId}
        connectionError={connectionError}
        onStartRun={startRun}
        onReset={reset}
      />

      <TokenPanel budget={budget} tokensByAgent={tokensByAgent} />

      <div className="main-content">
        <div className="graph-area">
          <GraphCanvas
            activeNode={activeNode}
            completedNodes={completedNodes}
            status={status}
            liveStatus={liveStatus}
          />
        </div>

        <div className="side-panel">
          <div className="tab-bar">
            {TABS.map(t => (
              <button
                key={t.id}
                className={`tab-btn ${tab === t.id ? "active" : ""}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
                {t.id === "files" && changedCount > 0 && (
                  <span className="tab-badge">{changedCount}</span>
                )}
              </button>
            ))}
          </div>

          <div className="tab-content">
            <div className={`tab-panel ${tab === "overview" ? "active" : ""}`}>
              <StateInspector state={state} />
            </div>
            <div className={`tab-panel ${tab === "files" ? "active" : ""}`}>
              <FileTree fileTree={fileTree} />
            </div>
            <div className={`tab-panel ${tab === "git" ? "active" : ""}`}>
              <GitPanel workspaceName={workspaceName} onRefreshFileTree={refreshFileTree} />
            </div>
            <div className={`tab-panel ${tab === "logs" ? "active" : ""}`}>
              <AgentActivity activity={activity} liveStatus={liveStatus} />
              <LogStream logs={logs} />
            </div>
          </div>
        </div>
      </div>

      {interruptPayload && (
        <InterruptModal
          payload={interruptPayload}
          onResume={resumeInterrupt}
        />
      )}
    </div>
  );
}
