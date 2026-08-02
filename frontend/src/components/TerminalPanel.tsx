import { useEffect, useRef } from "react";
import type { TerminalEntry } from "../types";

interface TerminalPanelProps {
  entries: TerminalEntry[];
}

export function TerminalPanel({ entries }: TerminalPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  return (
    <section className="panel terminal-panel" aria-labelledby="terminal-title">
      <div className="panel-heading terminal-heading">
        <div>
          <span className="eyebrow">Programmer / Docker stdout</span>
          <h2 id="terminal-title">Execution feed</h2>
        </div>
        <span className="terminal-lights"><i /><i /><i /></span>
      </div>
      <div className="terminal-body" role="log" aria-live="polite">
        {entries.length === 0 && (
          <div className="terminal-empty"><span>$</span> Waiting for sandbox output...</div>
        )}
        {entries.map((entry, index) => (
          <div className={`terminal-line terminal-${entry.stream}`} key={`${entry.ts}-${index}`}>
            <span className="terminal-prefix">{entry.stream === "stderr" ? "!" : "$"}</span>
            <span>{entry.text}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </section>
  );
}
