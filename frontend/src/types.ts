export interface LogEntry {
  timestamp: number;
  node: string;
  summary: string;
}

export interface InterruptPayload {
  kind?: "escalation" | "deploy";
  question: string;
  failures?: string[];
  test_output?: string;
  context_diff?: string;
  options: string[];
}

export type RunStatus = "idle" | "running" | "interrupted" | "done" | "error";

export type NodeResult = "success" | "error";

export interface ActivityEntry {
  ts: number;
  agent: string;
  msg: string;
  kind?: "info" | "stdout" | "stderr";
}

export interface CustomEventPayload {
  agent: string;
  msg: string;
  kind?: "info" | "stdout" | "stderr";
}

export interface TerminalEntry {
  ts: number;
  stream: "stdout" | "stderr";
  text: string;
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
  cost_usd: number;
  cost_cap_usd: number | null;
  tokens_by_provider?: Record<string, number>;
  cost_by_provider?: Record<string, number>;
  calls_by_provider?: Record<string, number>;
}

export interface ModelSelection {
  provider: string;
  model: string;
}

export interface RunConfig {
  primary: ModelSelection;
  fallbacks: ModelSelection[];
  timeout_minutes?: number;
}

export interface ProviderInfo {
  id: string;
  kind: string;
  label: string;
  default_model: string;
  base_url: string | null;
  enabled: boolean;
  models: string[];
  has_key: boolean;
  key_masked: string | null;
  is_default: boolean;
  fallback: boolean;
}

export interface RunRecord {
  id: string;
  threadId: string | null;
  startedAt: number;
  endedAt: number;
  status: RunStatus;
  projectName: string;
  spec: string;
  runConfig: RunConfig;
  budget: BudgetInfo | null;
  logs: LogEntry[];
  terminal: TerminalEntry[];
  artifact?: string;
}

export type AgentName =
  | "validator"
  | "base"
  | "planner"
  | "programmer"
  | "tester"
  | "escalation"
  | "deployer";

export type TabId = "overview" | "files" | "git" | "logs";
export type ScreenId = "console" | "escalation" | "providers" | "history" | "profile";
