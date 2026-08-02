import { useCallback, useEffect, useRef, useState } from "react";
import { createRun, resumeRun, streamRun, type StreamEvent } from "../api/run";
import type {
  ActivityEntry,
  BudgetInfo,
  CustomEventPayload,
  FileTreeEntry,
  InterruptPayload,
  LogEntry,
  NodeResult,
  RunConfig,
  RunRecord,
  RunStatus,
  TerminalEntry,
} from "../types";

function summarizeNodeOutput(node: string, data: Record<string, unknown>): string {
  if (node === "planner") {
    const plan = data.plan as { type?: string; steps?: unknown[] } | undefined;
    return `produced ${plan?.type ?? "?"} plan with ${plan?.steps?.length ?? 0} steps`;
  }
  if (node === "programmer") return "applied changes to workspace";
  if (node === "tester") {
    const report = data.test_report as { passed?: boolean; confidence?: number } | undefined;
    return report
      ? `${report.passed ? "PASS" : "FAIL"} with ${(report.confidence ?? 0).toFixed(2)} confidence`
      : "no report";
  }
  if (node === "escalation") return "human decision required";
  if (node === "validator") return data.status === "rejected" ? "spec rejected" : "spec validated";
  if (node === "base") return "sandbox workspace initialized";
  if (node === "advance") return "milestone complete";
  if (node === "cleanup") return "sandbox stopped";
  return JSON.stringify(data).slice(0, 100);
}

type StreamEvt = StreamEvent;

interface StreamConsumers {
  setStatus: (status: RunStatus) => void;
  setActiveNode: (node: string | null) => void;
  setCompletedNodes: (results: Record<string, NodeResult>) => void;
  setAccumState: (state: Record<string, unknown> | null) => void;
  setLogs: React.Dispatch<React.SetStateAction<LogEntry[]>>;
  setInterruptPayload: (payload: InterruptPayload | null) => void;
  setActivity: React.Dispatch<React.SetStateAction<ActivityEntry[]>>;
  setLiveStatus: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  setTokensByAgent: React.Dispatch<React.SetStateAction<Record<string, number>>>;
  setFileTree: React.Dispatch<React.SetStateAction<FileTreeEntry[]>>;
  setTerminal: React.Dispatch<React.SetStateAction<TerminalEntry[]>>;
  stateRef: React.MutableRefObject<Record<string, unknown>>;
  completedRef: React.MutableRefObject<Record<string, NodeResult>>;
}

function addLog(
  setLogs: React.Dispatch<React.SetStateAction<LogEntry[]>>,
  node: string,
  summary: string,
) {
  setLogs(previous => {
    const next = [...previous, { timestamp: Date.now(), node, summary }];
    return next.length > 300 ? next.slice(-300) : next;
  });
}

async function consumeStream(
  stream: AsyncIterable<StreamEvt>,
  consumers: StreamConsumers,
): Promise<boolean> {
  let previousNode: string | null = null;
  let receivedUpdates = false;

  for await (const evt of stream) {
    const event = evt.event;
    const data = evt.data as Record<string, unknown> | undefined;

    if (event === "metadata") {
      const runId = String(data?.run_id ?? "?");
      addLog(consumers.setLogs, "system", `stream connected · ${runId.slice(0, 8)}`);
      continue;
    }

    if (event === "error") {
      addLog(consumers.setLogs, "system", "stream interrupted by the backend");
      consumers.setStatus("error");
      consumers.setActiveNode(null);
      return false;
    }

    if (event === "custom" && data) {
      const payload = data as unknown as CustomEventPayload;
      if (!payload.agent || !payload.msg) continue;
      const kind = payload.kind ?? "info";
      consumers.setActivity(previous => {
        const next = [...previous, { ts: Date.now(), agent: payload.agent, msg: payload.msg, kind }];
        return next.length > 300 ? next.slice(-300) : next;
      });
      consumers.setLiveStatus(previous => ({ ...previous, [payload.agent]: payload.msg }));
      if (kind === "stdout" || kind === "stderr") {
        consumers.setTerminal(previous => {
          const next = [...previous, { ts: Date.now(), stream: kind, text: payload.msg }];
          return next.length > 500 ? next.slice(-500) : next;
        });
      }
      continue;
    }

    if (event !== "updates" || !data) continue;
    receivedUpdates = true;

    for (const [nodeName, nodeOutput] of Object.entries(data)) {
      if (nodeName === "__interrupt__") {
        const payload = (nodeOutput as { value: InterruptPayload }[])?.[0]?.value;
        if (payload) {
          consumers.setActiveNode("escalation");
          consumers.setInterruptPayload(payload);
          consumers.setStatus("interrupted");
          addLog(consumers.setLogs, "escalation", "human decision required");
          return true;
        }
        continue;
      }

      const output = (nodeOutput ?? {}) as Record<string, unknown>;
      if (previousNode && previousNode !== nodeName) {
        const previousOutput = consumers.stateRef.current;
        const result = previousOutput.status === "failed" || previousOutput.status === "rejected" ? "error" : "success";
        consumers.completedRef.current = { ...consumers.completedRef.current, [previousNode]: result };
        consumers.setCompletedNodes(consumers.completedRef.current);
      }
      consumers.setActiveNode(nodeName);
      previousNode = nodeName;
      consumers.stateRef.current = {
        ...consumers.stateRef.current,
        ...output,
        last_node: nodeName,
      };
      consumers.setAccumState(consumers.stateRef.current);
      addLog(consumers.setLogs, nodeName, summarizeNodeOutput(nodeName, output));

      if (output.file_tree) consumers.setFileTree(output.file_tree as FileTreeEntry[]);
      if (output.tokens_by_agent) consumers.setTokensByAgent(output.tokens_by_agent as Record<string, number>);
    }
  }

  if (previousNode) {
    const result = consumers.stateRef.current.status === "failed" ? "error" : "success";
    consumers.completedRef.current = { ...consumers.completedRef.current, [previousNode]: result };
    consumers.setCompletedNodes(consumers.completedRef.current);
  }
  if (!receivedUpdates) {
    addLog(consumers.setLogs, "system", "no run updates received");
    consumers.setStatus("error");
    consumers.setActiveNode(null);
    return false;
  }
  const finalState = String(consumers.stateRef.current.status ?? "");
  consumers.setStatus(finalState === "failed" || finalState === "rejected" ? "error" : "done");
  consumers.setActiveNode(null);
  return true;
}

const DEFAULT_RUN_CONFIG: RunConfig = {
  primary: { provider: "openai", model: "gpt-4o-mini" },
  fallbacks: [],
  timeout_minutes: 30,
};

interface UseLangGraphStream {
  status: RunStatus;
  activeNode: string | null;
  completedNodes: Record<string, NodeResult>;
  state: Record<string, unknown> | null;
  logs: LogEntry[];
  interruptPayload: InterruptPayload | null;
  threadId: string | null;
  connectionError: boolean;
  activity: ActivityEntry[];
  liveStatus: Record<string, string>;
  tokensByAgent: Record<string, number>;
  fileTree: FileTreeEntry[];
  terminal: TerminalEntry[];
  history: RunRecord[];
  startRun: (projectMd: string, sourcePath?: string, runConfig?: RunConfig) => Promise<void>;
  resumeInterrupt: (choice: string | { action: string; guidance?: string }) => Promise<void>;
  reset: () => void;
}

function readHistory(): RunRecord[] {
  try {
    const raw = localStorage.getItem("symbiot.run-history");
    if (!raw) return [];
    const parsed = JSON.parse(raw) as RunRecord[];
    return Array.isArray(parsed) ? parsed.slice(0, 30) : [];
  } catch {
    return [];
  }
}

function projectName(spec: string): string {
  const match = spec.match(/name:\s*([^|\n]+)/i);
  return match?.[1]?.trim() || "untitled mission";
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
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [liveStatus, setLiveStatus] = useState<Record<string, string>>({});
  const [tokensByAgent, setTokensByAgent] = useState<Record<string, number>>({});
  const [fileTree, setFileTree] = useState<FileTreeEntry[]>([]);
  const [terminal, setTerminal] = useState<TerminalEntry[]>([]);
  const [history, setHistory] = useState<RunRecord[]>(readHistory);
  const [runId, setRunId] = useState<string | null>(null);

  const threadIdRef = useRef<string | null>(null);
  const stateRef = useRef<Record<string, unknown>>({});
  const completedRef = useRef<Record<string, NodeResult>>({});
  const specRef = useRef("");
  const runConfigRef = useRef<RunConfig>(DEFAULT_RUN_CONFIG);
  const startedAtRef = useRef(0);
  const pendingInterruptRef = useRef<InterruptPayload | null>(null);

  const consumers = useCallback((): StreamConsumers => ({
    setStatus,
    setActiveNode,
    setCompletedNodes,
    setAccumState,
    setLogs,
    setInterruptPayload,
    setActivity,
    setLiveStatus,
    setTokensByAgent,
    setFileTree,
    setTerminal,
    stateRef,
    completedRef,
  }), []);

  const startRun = useCallback(async (projectMd: string, sourcePath?: string, runConfig?: RunConfig) => {
    const selectedConfig = runConfig ?? DEFAULT_RUN_CONFIG;
    const nextRunId = crypto.randomUUID();
    specRef.current = projectMd;
    runConfigRef.current = selectedConfig;
    startedAtRef.current = Date.now();
    setRunId(nextRunId);
    setConnectionError(false);
    setStatus("running");
    setActiveNode(null);
    setCompletedNodes({});
    setAccumState(null);
    setLogs([]);
    setInterruptPayload(null);
    setActivity([]);
    setLiveStatus({});
    setTokensByAgent({});
    setFileTree([]);
    setTerminal([]);
    stateRef.current = {};
    completedRef.current = {};
    pendingInterruptRef.current = null;

    try {
      const run = await createRun({
        raw_spec: projectMd,
        run_config: selectedConfig,
        ...(sourcePath ? { source_path: sourcePath } : {}),
      });
      threadIdRef.current = run.run_id;
      setThreadId(run.run_id);
      await consumeStream(streamRun(run.run_id), consumers());
    } catch {
      setConnectionError(true);
      setStatus("error");
      setActiveNode(null);
      addLog(setLogs, "system", "cannot reach the symbiot run service");
    }
  }, [consumers]);

  const resumeInterrupt = useCallback(async (choice: string | { action: string; guidance?: string }) => {
    const previous = interruptPayload;
    pendingInterruptRef.current = previous;
    setConnectionError(false);
    setStatus("running");
    setInterruptPayload(null);
    try {
      const tid = threadIdRef.current;
      if (!tid) throw new Error("missing run thread");
      const response = await resumeRun(tid, choice);
      const ok = await consumeStream(streamRun(tid, response.cursor), consumers());
      if (!ok && previous) {
        setInterruptPayload(previous);
        setStatus("interrupted");
      }
    } catch {
      if (previous) {
        setInterruptPayload(previous);
        setStatus("interrupted");
      } else {
        setStatus("error");
      }
      addLog(setLogs, "system", "human action could not be applied");
    }
  }, [consumers, interruptPayload]);

  useEffect(() => {
    if (!runId || !["done", "error", "interrupted"].includes(status)) return;
    const stateBudget = accumState?.budget as Partial<BudgetInfo> | undefined;
    const budget: BudgetInfo | null = stateBudget
      ? {
          tokens_used: Number(stateBudget.tokens_used ?? 0),
          token_cap: Number(stateBudget.token_cap ?? 0),
          llm_calls: Number(stateBudget.llm_calls ?? 0),
          llm_call_cap: Number(stateBudget.llm_call_cap ?? 0),
          cost_usd: Number(stateBudget.cost_usd ?? 0),
          cost_cap_usd: stateBudget.cost_cap_usd == null ? null : Number(stateBudget.cost_cap_usd),
          tokens_by_provider: stateBudget.tokens_by_provider,
          cost_by_provider: stateBudget.cost_by_provider,
          calls_by_provider: stateBudget.calls_by_provider,
        }
      : null;
    const record: RunRecord = {
      id: runId,
      threadId,
      startedAt: startedAtRef.current,
      endedAt: Date.now(),
      status,
      projectName: projectName(specRef.current),
      spec: specRef.current,
      runConfig: runConfigRef.current,
      budget,
      logs,
      terminal,
      artifact: typeof accumState?.deploy_result === "object" ? "Docker image produced" : undefined,
    };
    setHistory(previous => {
      const next = [record, ...previous.filter(item => item.id !== runId)].slice(0, 30);
      localStorage.setItem("symbiot.run-history", JSON.stringify(next));
      return next;
    });
  }, [accumState, logs, runId, status, terminal, threadId]);

  const reset = useCallback(() => {
    setStatus("idle");
    setActiveNode(null);
    setCompletedNodes({});
    setAccumState(null);
    setLogs([]);
    setInterruptPayload(null);
    setThreadId(null);
    setConnectionError(false);
    setActivity([]);
    setLiveStatus({});
    setTokensByAgent({});
    setFileTree([]);
    setTerminal([]);
    setRunId(null);
    threadIdRef.current = null;
    stateRef.current = {};
    completedRef.current = {};
  }, []);

  return {
    status,
    activeNode,
    completedNodes,
    state: accumState,
    logs,
    interruptPayload,
    threadId,
    connectionError,
    activity,
    liveStatus,
    tokensByAgent,
    fileTree,
    terminal,
    history,
    startRun,
    resumeInterrupt,
    reset,
  };
}
