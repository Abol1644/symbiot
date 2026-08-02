export interface LogEntry {
  timestamp: number;
  node: string;
  summary: string;
}

export interface InterruptPayload {
  question: string;
  failures?: string[];
  options: string[];
}

export type RunStatus = "idle" | "running" | "interrupted" | "done" | "error";

export type NodeResult = "success" | "error";

export interface ActivityEntry {
  ts: number;
  agent: string;
  msg: string;
}

export interface CustomEventPayload {
  agent: string;
  msg: string;
}

export interface FileTreeEntry {
  path: string;
  status: "existing" | "created" | "modified";
}

export interface BudgetInfo {
  tokens_used: number;
  token_cap: number;
  llm_calls: number;
  llm_call_cap: number;
}

export type AgentName = "validator" | "base" | "planner" | "programmer" | "tester" | "escalation" | "deployer";

export type TabId = "overview" | "files" | "git" | "logs";
