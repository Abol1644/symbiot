import { useMemo, type ReactNode } from "react";

function formatState(key: string, value: unknown): string {
  if (key === "plan" && typeof value === "object" && value !== null) {
    const plan = value as Record<string, unknown>;
    const steps = plan.steps as unknown[] | undefined;
    return JSON.stringify({ ...plan, steps: `[${steps?.length ?? 0} steps]` }, null, 2);
  }
  if (key === "milestones" && Array.isArray(value)) {
    return JSON.stringify(value.map((m: Record<string, unknown>) => ({ id: m.id, title: m.title })), null, 2);
  }
  if (key === "raw_spec" && typeof value === "string") {
    const lines = value.split("\n");
    if (lines.length > 6) {
      return lines.slice(0, 6).join("\n") + `\n... (${lines.length - 6} more lines)`;
    }
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function colorizedJson(json: string): ReactNode[] {
  return json.split("\n").map((line, i) => {
    const match = line.match(/^(\s*)"([^"]+)"(\s*:\s*)(.*)/);
    if (match) {
      return (
        <div key={i}>
          {match[1]}<span className="state-key">&quot;{match[2]}&quot;</span>{match[3]}
          <span className={
            /^".*"$/.test(match[4].trim().replace(/,$/, "")) ? "state-string" :
            /^\d+/.test(match[4].trim().replace(/,$/, "")) ? "state-number" :
            /^(true|false)/.test(match[4].trim()) ? "state-bool" : ""
          }>{match[4]}</span>
        </div>
      );
    }
    return <div key={i}>{line}</div>;
  });
}

interface StateInspectorProps {
  state: Record<string, unknown> | null;
}

export function StateInspector({ state }: StateInspectorProps) {
  const budget = useMemo(() => {
    if (!state?.budget) return null;
    const b = state.budget as { tokens_used?: number; token_cap?: number; llm_calls?: number; llm_call_cap?: number };
    return {
      tokens_used: b.tokens_used ?? 0,
      token_cap: b.token_cap ?? 0,
      llm_calls: b.llm_calls ?? 0,
      llm_call_cap: b.llm_call_cap ?? 0,
    };
  }, [state]);

  const deploy = useMemo(() => {
    if (!state?.deploy_result) return null;
    return state.deploy_result as { image?: string; tag?: string; smoke_test_passed?: boolean; smoke_test_output?: string };
  }, [state]);

  const tokenPct = budget && budget.token_cap > 0 ? Math.min(100, (budget.tokens_used / budget.token_cap) * 100) : 0;
  const callPct = budget && budget.llm_call_cap > 0 ? Math.min(100, (budget.llm_calls / budget.llm_call_cap) * 100) : 0;

  return (
    <div className="state-inspector">
      <div className="state-header">State</div>

      {deploy && (
        <div className="deploy-card">
          <div className="deploy-image">
            <span className="state-key">image</span>{" "}
            <code>{deploy.image}:{deploy.tag}</code>
          </div>
          <div className={`deploy-smoke ${deploy.smoke_test_passed ? "pass" : "fail"}`}>
            smoke test: {deploy.smoke_test_passed ? "PASS" : "FAIL"}
          </div>
          {deploy.smoke_test_output && (
            <pre className="deploy-output">{deploy.smoke_test_output}</pre>
          )}
        </div>
      )}

      {budget && (
        <>
          <div className="budget-bar-wrap">
            <span>tokens</span>
            <div className="budget-bar">
              <div
                className={`budget-bar-fill${tokenPct > 90 ? " error" : tokenPct > 70 ? " warn" : ""}`}
                style={{ width: `${tokenPct}%` }}
              />
            </div>
            <span>{budget.tokens_used.toLocaleString()} / {budget.token_cap.toLocaleString()}</span>
          </div>
          <div className="budget-bar-wrap">
            <span>calls</span>
            <div className="budget-bar">
              <div
                className={`budget-bar-fill${callPct > 90 ? " error" : callPct > 70 ? " warn" : ""}`}
                style={{ width: `${callPct}%` }}
              />
            </div>
            <span>{budget.llm_calls} / {budget.llm_call_cap}</span>
          </div>
        </>
      )}

      {state && (
        <div className="state-json">
          {Object.entries(state)
            .filter(([k]) => k !== "budget" && k !== "raw_spec")
            .map(([key, value]) => (
              <div key={key} style={{ marginBottom: 8 }}>
                {colorizedJson(formatState(key, value))}
              </div>
            ))}
        </div>
      )}

      {!state && (
        <div className="empty-state" style={{ padding: 40 }}>
          <span className="icon">{"{}"}</span>
          <span>No state yet</span>
        </div>
      )}
    </div>
  );
}
