import { useEffect, useRef } from "react";
import type { ActivityEntry } from "../types";

const AGENT_COLORS: Record<string, string> = {
  validator: "var(--agent-slate)",
  base: "var(--agent-teal)",
  planner: "var(--agent-cyan)",
  programmer: "var(--agent-amber)",
  tester: "var(--agent-green)",
  escalation: "var(--agent-orange)",
  deployer: "var(--agent-violet)",
  system: "var(--muted)",
};

interface AgentActivityProps {
  activity: ActivityEntry[];
  liveStatus: Record<string, string>;
}

export function AgentActivity({ activity, liveStatus }: AgentActivityProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activity]);

  const liveAgents = Object.entries(liveStatus);

  return (
    <div className="agent-activity">
      <div className="panel-header">Activity</div>

      {liveAgents.length > 0 && (
        <div className="live-now">
          {liveAgents.map(([agent, msg]) => (
            <div key={agent} className="live-now-line">
              <span
                className="agent-dot"
                style={{ backgroundColor: AGENT_COLORS[agent] ?? "var(--muted)" }}
              />
              <span className="agent-name" style={{ color: AGENT_COLORS[agent] ?? "var(--muted)" }}>
                {agent}
              </span>
              <span className="agent-msg">{msg}</span>
            </div>
          ))}
        </div>
      )}

      <div className="activity-feed">
        {activity.length === 0 && (
          <div className="activity-empty">Waiting for agent activity...</div>
        )}
        {activity.map((entry, i) => (
          <div key={i} className="activity-entry">
            <span className="activity-ts">
              {new Date(entry.ts).toLocaleTimeString()}
            </span>
            <span
              className="activity-agent"
              style={{ color: AGENT_COLORS[entry.agent] ?? "var(--muted)" }}
            >
              {entry.agent}
            </span>
            <span className="activity-msg">{entry.msg}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
