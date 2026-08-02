import { describe, expect, it } from "vitest";
import { budgetFromState, budgetPercent, missionName } from "./mission";

describe("mission utilities", () => {
  it("extracts a safe project name from PROJECT.md metadata", () => {
    expect(missionName("## META\nname: launch-pad | stack: python")).toBe("launch-pad");
    expect(missionName("no metadata")).toBe("untitled mission");
  });

  it("clamps budget bars to the guardrail range", () => {
    expect(budgetPercent(50, 100)).toBe(50);
    expect(budgetPercent(120, 100)).toBe(100);
    expect(budgetPercent(-1, 100)).toBe(0);
    expect(budgetPercent(1, 0)).toBe(0);
  });

  it("normalizes streamed budget state without exposing unrelated fields", () => {
    expect(budgetFromState({ budget: { tokens_used: 20, token_cap: 100, cost_usd: 0.02 } })).toEqual({
      tokens_used: 20,
      token_cap: 100,
      llm_calls: 0,
      llm_call_cap: 0,
      cost_usd: 0.02,
      cost_cap_usd: null,
      tokens_by_provider: undefined,
      cost_by_provider: undefined,
      calls_by_provider: undefined,
    });
    expect(budgetFromState(null)).toBeNull();
  });
});
