import type { RunConfig } from "../types";

const BASE = (import.meta.env.VITE_RUN_API_URL ?? "/api").replace(/\/$/, "");

export interface RunStartInput {
  raw_spec: string;
  source_path?: string;
  run_config: RunConfig;
}

interface RunStartResponse {
  run_id: string;
  status: string;
}

interface ResumeResponse {
  run_id: string;
  cursor: number;
  status: string;
}

export interface StreamEvent {
  event?: string;
  data?: unknown;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`run service returned ${response.status}`);
  return response.json() as Promise<T>;
}

export async function createRun(input: RunStartInput): Promise<RunStartResponse> {
  const response = await fetch(`${BASE}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readJson<RunStartResponse>(response);
}

export async function resumeRun(runId: string, decision: string | { action: string; guidance?: string }): Promise<ResumeResponse> {
  const response = await fetch(`${BASE}/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  return readJson<ResumeResponse>(response);
}

export async function* streamRun(runId: string, after = 0): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${BASE}/runs/${encodeURIComponent(runId)}/events?after=${after}`, {
    headers: { Accept: "text/event-stream" },
  });
  if (!response.ok || !response.body) throw new Error(`run event stream returned ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const lines = frame.split("\n");
        let event = "message";
        const dataLines: string[] = [];
        for (const line of lines) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;
        try {
          yield { event, data: JSON.parse(dataLines.join("\n")) as unknown };
        } catch {
          yield { event, data: dataLines.join("\n") };
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
