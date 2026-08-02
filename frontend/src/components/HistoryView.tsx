import { useState } from "react";
import type { RunRecord } from "../types";

interface HistoryViewProps {
  records: RunRecord[];
  onRerun: (record: RunRecord) => void;
}

function formatDate(timestamp: number): string {
  return new Date(timestamp).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function HistoryView({ records, onRerun }: HistoryViewProps) {
  const [selected, setSelected] = useState<RunRecord | null>(records[0] ?? null);
  return (
    <section className="screen history-screen" aria-labelledby="history-title">
      <div className="screen-heading"><div><span className="eyebrow">Archive / evidence</span><h1 id="history-title">Run history</h1><p>Every mission leaves behind its route, burn, output, and decision trail.</p></div><span className="count-badge">{records.length} missions</span></div>
      <div className="history-layout">
        <div className="history-list panel">
          <div className="panel-heading"><div><span className="eyebrow">Recent missions</span><h2>Flight log</h2></div></div>
          {records.length === 0 && <div className="empty-inline">No completed missions yet. Start from the console.</div>}
          {records.map(record => (
            <button className={`history-row ${selected?.id === record.id ? "selected" : ""}`} key={record.id} onClick={() => setSelected(record)}>
              <span className={`history-status status-${record.status}`} />
              <span className="history-main"><strong>{record.projectName}</strong><small>{record.runConfig.primary.provider} / {record.runConfig.primary.model}</small></span>
              <span className="history-meta"><strong>{record.status}</strong><small>{formatDate(record.endedAt)}</small></span>
            </button>
          ))}
        </div>
        <div className="panel history-detail">
          {selected ? (
            <>
              <div className="panel-heading"><div><span className="eyebrow">Mission record</span><h2>{selected.projectName}</h2></div><button className="button button-small" onClick={() => onRerun(selected)}>Re-run mission</button></div>
              <div className="detail-grid">
                <div><span>status</span><strong>{selected.status}</strong></div>
                <div><span>started</span><strong>{formatDate(selected.startedAt)}</strong></div>
                <div><span>provider</span><strong>{selected.runConfig.primary.provider}</strong></div>
                <div><span>model</span><strong>{selected.runConfig.primary.model}</strong></div>
                <div><span>tokens</span><strong>{selected.budget?.tokens_used.toLocaleString() ?? "--"}</strong></div>
                <div><span>cost</span><strong>{selected.budget ? `$${selected.budget.cost_usd.toFixed(4)}` : "--"}</strong></div>
              </div>
              <div className="history-section"><div className="evidence-label">Event trail</div><div className="history-log">{selected.logs.slice(-12).map((log, index) => <div key={`${log.timestamp}-${index}`}><time>{new Date(log.timestamp).toLocaleTimeString()}</time><b>{log.node}</b><span>{log.summary}</span></div>)}</div></div>
              {selected.terminal.length > 0 && <div className="history-section"><div className="evidence-label">Artifact stream</div><pre className="history-terminal">{selected.terminal.map(entry => entry.text).join("\n")}</pre></div>}
            </>
          ) : <div className="empty-screen"><div className="empty-glyph">00</div><h2>Select a mission</h2><p>Run evidence will appear here.</p></div>}
        </div>
      </div>
    </section>
  );
}
