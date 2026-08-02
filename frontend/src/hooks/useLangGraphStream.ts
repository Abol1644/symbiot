import { useState, useRef, useCallback } from "react";
import { Client } from "@langchain/langgraph-sdk";
import type { LogEntry, InterruptPayload, RunStatus, NodeResult } from "../types";

const client = new Client({ apiUrl: "http://127.0.0.1:2024" });

function summarizeNodeOutput(node: string, data: Record<string, unknown>): string {
  if (node === "planner") {
    const plan = data.plan as { type?: string; steps?: unknown[] } | undefined;
    return `produced Plan(type=${plan?.type ?? "?"}, ${plan?.steps?.length ?? 0} steps)`;
  }
  if (node === "programmer") return "applied changes to workspace";
  if (node === "tester") {
    const tr = data.test_report as { passed?: boolean; confidence?: number } | undefined;
    return tr ? `${tr.passed ? "PASS" : "FAIL"} (conf=${(tr.confidence ?? 0).toFixed(2)})` : "no report";
  }
  if (node === "escalation") return data.status_reason ? `abort: ${data.status_reason}` : "escalation";
  if (node === "validator") return data.status === "rejected" ? "rejected" : "validated";
  if (node === "base") return "workspace initialized";
  if (node === "advance") return "milestone done, advancing";
  if (node === "cleanup") return "sandbox stopped";
  return JSON.stringify(data).slice(0, 80);
}

type StreamEvt = { event?: string; data?: unknown };

interface StreamConsumers {
  setStatus: (s: RunStatus) => void;
  setActiveNode: (n: string | null) => void;
  setCompletedNodes: (r: Record<string, NodeResult>) => void;
  setAccumState: (s: Record<string, unknown> | null) => void;
  setLogs: React.Dispatch<React.SetStateAction<LogEntry[]>>;
  setInterruptPayload: (p: InterruptPayload | null) => void;
  stateRef: React.MutableRefObject<Record<string, unknown>>;
  completedRef: React.MutableRefObject<Record<string, NodeResult>>;
}

async function consumeStream(
  stream: AsyncIterable<StreamEvt>,
  c: StreamConsumers,
) {
  let prevNode: string | null = null;
  let receivedUpdates = false;

  for await (const evt of stream) {
    const e = evt.event;
    const d = evt.data as Record<string, unknown> | undefined;

    if (e === "metadata") {
      const meta = d as { run_id?: string } | undefined;
      c.setLogs(prev => [...prev.slice(-199), { timestamp: Date.now(), node: "system", summary: `run ${meta?.run_id?.slice(0, 8) ?? "?"}...` }]);
      continue;
    }

    if (e === "error") {
      c.setLogs(prev => [...prev.slice(-199), { timestamp: Date.now(), node: "system", summary: `error: ${String(d)}` }]);
      c.setStatus("error");
      return;
    }

    if (e === "updates" && d) {
      receivedUpdates = true;

      for (const [nodeName, nodeOutput] of Object.entries(d)) {
        if (nodeName === "__interrupt__") {
          const val = (nodeOutput as { value: InterruptPayload }[])?.[0]?.value;
          if (val) { c.setInterruptPayload(val); c.setStatus("interrupted"); return; }
          continue;
        }

        const out = nodeOutput as Record<string, unknown>;

        if (prevNode && prevNode !== nodeName) {
          const isError = out?.status === "failed";
          c.completedRef.current = { ...c.completedRef.current, [prevNode]: isError ? "error" : "success" };
          c.setCompletedNodes(c.completedRef.current);
        }

        c.setActiveNode(nodeName);
        prevNode = nodeName;

        c.stateRef.current = { ...c.stateRef.current, [nodeName]: out };
        c.setAccumState(c.stateRef.current);

        c.setLogs(prev => {
          const entry: LogEntry = { timestamp: Date.now(), node: nodeName, summary: summarizeNodeOutput(nodeName, out) };
          const next = [...prev, entry];
          return next.length > 200 ? next.slice(next.length - 200) : next;
        });
      }
      continue;
    }
  }

  if (prevNode) {
    c.completedRef.current = { ...c.completedRef.current, [prevNode]: "success" };
    c.setCompletedNodes(c.completedRef.current);
  }

  if (!receivedUpdates) {
    c.setStatus("error");
    c.setLogs(prev => [...prev.slice(-199), { timestamp: Date.now(), node: "system", summary: "no updates received — server may have errored" }]);
  } else {
    c.setStatus("done");
  }
  c.setActiveNode(null);
}

interface UseLangGraphStream {
  status: RunStatus;
  activeNode: string | null;
  completedNodes: Record<string, NodeResult>;
  state: Record<string, unknown> | null;
  logs: LogEntry[];
  interruptPayload: InterruptPayload | null;
  threadId: string | null;
  connectionError: boolean;
  startRun: (projectMd: string) => Promise<void>;
  resumeInterrupt: (choice: string) => Promise<void>;
  reset: () => void;
}

export function useLangGraphStream(): UseLangGraphStream {
  const [status, setStatus] = useState<RunStatus>("idle");
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [completedNodes, setCompletedNodes] = useState<Record<string, NodeResult>>({});
  const [accumState, setAccumState] = useState<Record<string, unknown> | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [interruptPayload, setInterruptPayload] = useState<InterruptPayload | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState(false);

  const threadIdRef = useRef<string | null>(null);
  const stateRef = useRef<Record<string, unknown>>({});
  const completedRef = useRef<Record<string, NodeResult>>({});

  const startRun = useCallback(async (projectMd: string) => {
    setConnectionError(false);
    setStatus("running");
    setActiveNode(null);
    setCompletedNodes({});
    setAccumState(null);
    setLogs([]);
    setInterruptPayload(null);
    stateRef.current = {};
    completedRef.current = {};

    try {
      const thread = await client.threads.create();
      threadIdRef.current = thread.thread_id;
      setThreadId(thread.thread_id);

      const stream = client.runs.stream(thread.thread_id, "loop", {
        input: { raw_spec: projectMd },
        streamMode: "updates" as const,
      });

      await consumeStream(stream as AsyncIterable<StreamEvt>, {
        setStatus, setActiveNode, setCompletedNodes, setAccumState, setLogs, setInterruptPayload,
        stateRef, completedRef,
      });
    } catch (err) {
      console.error("[symbiot]", err);
      if (err instanceof TypeError || String(err).includes("fetch")) {
        setConnectionError(true);
      }
      setStatus("error");
      setActiveNode(null);
    }
  }, []);

  const resumeInterrupt = useCallback(async (choice: string) => {
    setConnectionError(false);
    setStatus("running");
    setInterruptPayload(null);

    try {
      const tid = threadIdRef.current;
      if (!tid) return;

      const stream = client.runs.stream(tid, "loop", {
        command: { resume: choice } as { resume: string },
        streamMode: "updates" as const,
      });

      await consumeStream(stream as AsyncIterable<StreamEvt>, {
        setStatus, setActiveNode, setCompletedNodes, setAccumState, setLogs, setInterruptPayload,
        stateRef, completedRef,
      });
    } catch (err) {
      console.error("[symbiot]", err);
      if (err instanceof TypeError || String(err).includes("fetch")) {
        setConnectionError(true);
      }
      setStatus("error");
      setActiveNode(null);
    }
  }, []);

  const reset = useCallback(() => {
    setStatus("idle");
    setActiveNode(null);
    setCompletedNodes({});
    setAccumState(null);
    setLogs([]);
    setInterruptPayload(null);
    setThreadId(null);
    setConnectionError(false);
    threadIdRef.current = null;
    stateRef.current = {};
    completedRef.current = {};
  }, []);

  return { status, activeNode, completedNodes, state: accumState, logs, interruptPayload, threadId, connectionError, startRun, resumeInterrupt, reset };
}
