import type { NodeResult, RunStatus } from "../types";

const AGENTS = [
  { id: "validator", label: "Validator", detail: "spec integrity" },
  { id: "base", label: "Base", detail: "workspace + sandbox" },
  { id: "planner", label: "Planner", detail: "milestone plan" },
  { id: "programmer", label: "Programmer", detail: "changes in Docker" },
  { id: "tester", label: "Tester", detail: "proof + confidence" },
  { id: "deployer", label: "Deployer", detail: "approved artifact" },
] as const;

interface PipelineRailProps {
  activeNode: string | null;
  completedNodes: Record<string, NodeResult>;
  liveStatus: Record<string, string>;
  runStatus: RunStatus;
}

function nodeStatus(
  id: string,
  activeNode: string | null,
  completedNodes: Record<string, NodeResult>,
  runStatus: RunStatus,
): "queued" | "running" | "pass" | "fail" | "escalated" {
  if (runStatus === "interrupted" && id === "escalation") return "escalated";
  if (id === activeNode) return "running";
  if (completedNodes[id] === "error") return "fail";
  if (completedNodes[id] === "success") return "pass";
  return "queued";
}

export function PipelineRail({ activeNode, completedNodes, liveStatus, runStatus }: PipelineRailProps) {
  return (
    <section className="panel pipeline-panel" aria-labelledby="pipeline-title">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Factory route</span>
          <h2 id="pipeline-title">Mission pipeline</h2>
        </div>
        <span className="live-indicator"><span /> live stream</span>
      </div>
      <div className="pipeline-rail">
        {AGENTS.map((agent, index) => {
          const status = nodeStatus(agent.id, activeNode, completedNodes, runStatus);
          return (
            <div className="pipeline-step" key={agent.id}>
              <div className={`pipeline-node node-${status}`} aria-label={`${agent.label}: ${status}`}>
                <span className="node-index">0{index + 1}</span>
                <span className="node-mark" aria-hidden="true">
                  {status === "pass" ? "OK" : status === "fail" ? "!" : status === "escalated" ? "?" : status === "running" ? ".." : "--"}
                </span>
                <span className="node-copy">
                  <strong>{agent.label}</strong>
                  <small>{agent.detail}</small>
                </span>
                <span className="node-status">{status}</span>
                {liveStatus[agent.id] && status === "running" && (
                  <span className="node-live">{liveStatus[agent.id]}</span>
                )}
              </div>
              {index < AGENTS.length - 1 && <span className={`pipeline-link ${status === "pass" ? "link-pass" : ""}`} aria-hidden="true" />}
            </div>
          );
        })}
      </div>
      <div className="pipeline-legend" aria-label="Pipeline status legend">
        <span><i className="legend-dot dot-running" /> running</span>
        <span><i className="legend-dot dot-pass" /> pass</span>
        <span><i className="legend-dot dot-fail" /> fail</span>
        <span><i className="legend-dot dot-escalated" /> human gate</span>
      </div>
    </section>
  );
}
