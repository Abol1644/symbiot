import { useMemo } from "react";
import type { BudgetInfo } from "../types";

const AGENT_COLORS: Record<string, string> = {
  planner: "var(--agent-cyan)",
  programmer: "var(--agent-amber)",
  tester: "var(--agent-green)",
  base: "var(--agent-teal)",
};

interface TokenPanelProps {
  budget: BudgetInfo | null;
  tokensByAgent: Record<string, number>;
}

export function TokenPanel({ budget, tokensByAgent }: TokenPanelProps) {
  const tokenPct = budget && budget.token_cap > 0
    ? Math.min(100, (budget.tokens_used / budget.token_cap) * 100)
    : 0;

  const sortedAgents = useMemo(() => {
    return Object.entries(tokensByAgent).sort(([, a], [, b]) => b - a);
  }, [tokensByAgent]);

  const totalAgentTokens = sortedAgents.reduce((sum, [, t]) => sum + t, 0);

  return (
    <div className="vitals-strip">
      {budget && (
        <>
          <div className="vitals-item">
            <span className="vitals-label">tokens</span>
            <div className="vitals-bar">
              <div
                className={`vitals-bar-fill${tokenPct > 90 ? " error" : tokenPct > 70 ? " warn" : ""}`}
                style={{ width: `${tokenPct}%` }}
              />
            </div>
            <span className="vitals-value">{budget.tokens_used.toLocaleString()}/{budget.token_cap.toLocaleString()}</span>
          </div>
          <div className="vitals-item">
            <span className="vitals-label">calls</span>
            <span className="vitals-value">{budget.llm_calls}</span>
          </div>
        </>
      )}

      {sortedAgents.length > 0 && (
        <div className="vitals-item vitals-agents">
          {sortedAgents.map(([agent, tokens]) => {
            const pct = totalAgentTokens > 0 ? (tokens / totalAgentTokens) * 100 : 0;
            const color = AGENT_COLORS[agent] ?? "var(--muted)";
            return (
              <div key={agent} className="vitals-agent">
                <span className="vitals-agent-label" style={{ color }}>{agent}</span>
                <div className="vitals-agent-bar">
                  <div
                    className="vitals-agent-fill"
                    style={{ width: `${pct}%`, backgroundColor: color }}
                  />
                </div>
                <span className="vitals-agent-val">{tokens.toLocaleString()}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
