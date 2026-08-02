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
