import { useState } from "react";
import type { RunStatus } from "../types";

const DEFAULT_SPEC = `## META
name: todo-cli | stack: python 3.12 | runtime: cli

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

interface ControlPanelProps {
  status: RunStatus;
  threadId: string | null;
  connectionError: boolean;
  onStartRun: (spec: string) => void;
  onReset: () => void;
}

export function ControlPanel({ status, threadId, connectionError, onStartRun, onReset }: ControlPanelProps) {
  const [specText, setSpecText] = useState(DEFAULT_SPEC);
  const [showSpec, setShowSpec] = useState(false);

  const isRunning = status === "running";

  return (
    <>
      <div className="control-panel">
        <span className="brand">symbiot</span>

        <button
          className={`btn btn-run`}
          disabled={isRunning}
          onClick={() => setShowSpec(true)}
        >
          Run
        </button>

        <button
          className="btn"
          disabled={isRunning}
          onClick={onReset}
        >
          Reset
        </button>

        <span className={`status-badge status-${status}`}>{status}</span>

        {connectionError && (
          <span className="connection-error" style={{ padding: "3px 10px", margin: 0, fontSize: 12 }}>
            Cannot reach server — is `langgraph dev` running?
          </span>
        )}

        {threadId && (
          <span className="thread-id">thread: {threadId.slice(0, 12)}...</span>
        )}
      </div>

      {showSpec && (
        <div className="spec-modal" onClick={(e) => { if (e.target === e.currentTarget) setShowSpec(false); }}>
          <div className="spec-modal-card">
            <h2>PROJECT.md</h2>
            <textarea
              value={specText}
              onChange={(e) => setSpecText(e.target.value)}
              spellCheck={false}
            />
            <div className="spec-modal-actions">
              <button className="btn" onClick={() => setShowSpec(false)}>Cancel</button>
              <button
                className="btn btn-run"
                onClick={() => {
                  setShowSpec(false);
                  onStartRun(specText);
                }}
              >
                Start Run
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
