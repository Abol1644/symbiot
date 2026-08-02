import { useEffect, useRef } from "react";
import type { LogEntry } from "../types";

const NODE_COLORS: Record<string, string> = {
  planner: "log-planner",
  programmer: "log-programmer",
  tester: "log-tester",
  escalation: "log-escalation",
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toTimeString().slice(0, 8);
}

interface LogStreamProps {
  logs: LogEntry[];
}

export function LogStream({ logs }: LogStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <>
      <div className="panel-header">Logs</div>
      <div className="log-stream">
        {logs.length === 0 && (
          <div className="empty-state" style={{ padding: 40 }}>
            <span className="icon">{">_"}</span>
            <span>Waiting for events</span>
          </div>
        )}
        {logs.map((entry, i) => {
          const colorClass = NODE_COLORS[entry.node] ?? "log-info";
          return (
            <div className="log-entry" key={`${entry.timestamp}-${i}`}>
              <span className="log-time">[{formatTime(entry.timestamp)}]</span>
              <span className={colorClass}>{entry.node}</span>
              <span className="log-info"> &rarr; {entry.summary}</span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </>
  );
}
