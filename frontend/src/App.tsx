import { useLangGraphStream } from "./hooks/useLangGraphStream";
import { GraphCanvas } from "./components/GraphCanvas";
import { StateInspector } from "./components/StateInspector";
import { LogStream } from "./components/LogStream";
import { ControlPanel } from "./components/ControlPanel";
import { InterruptModal } from "./components/InterruptModal";

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
    startRun,
    resumeInterrupt,
    reset,
  } = useLangGraphStream();

  return (
    <div className="app-layout">
      <ControlPanel
        status={status}
        threadId={threadId}
        connectionError={connectionError}
        onStartRun={startRun}
        onReset={reset}
      />

      <div className="main-content">
        <div className="graph-area">
          <GraphCanvas
            activeNode={activeNode}
            completedNodes={completedNodes}
            status={status}
          />
        </div>

        <div className="side-panel">
          <StateInspector state={state} />
          <LogStream logs={logs} />
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
