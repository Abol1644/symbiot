import type { BudgetInfo } from "../types";

export function missionName(spec: string): string {
  return spec.match(/name:\s*([^|\n]+)/i)?.[1]?.trim() || "untitled mission";
}

export function budgetPercent(value: number, cap: number): number {
  if (cap <= 0) return 0;
  return Math.min(100, Math.max(0, value / cap * 100));
}

export function budgetFromState(state: Record<string, unknown> | null): BudgetInfo | null {
  const raw = state?.budget as Partial<BudgetInfo> | undefined;
  if (!raw) return null;
  return {
    tokens_used: Number(raw.tokens_used ?? 0),
    token_cap: Number(raw.token_cap ?? 0),
    llm_calls: Number(raw.llm_calls ?? 0),
    llm_call_cap: Number(raw.llm_call_cap ?? 0),
    cost_usd: Number(raw.cost_usd ?? 0),
    cost_cap_usd: raw.cost_cap_usd == null ? null : Number(raw.cost_cap_usd),
    tokens_by_provider: raw.tokens_by_provider,
    cost_by_provider: raw.cost_by_provider,
    calls_by_provider: raw.calls_by_provider,
  };
}
