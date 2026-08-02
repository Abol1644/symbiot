import { useEffect, useRef, useState } from "react";
import type { InterruptPayload } from "../types";

interface EscalationCenterProps {
  payload: InterruptPayload | null;
  onAction: (choice: string | { action: string; guidance?: string }) => void;
}

function isDeploy(payload: InterruptPayload): boolean {
  return payload.kind === "deploy" || (payload.options.includes("deploy") && payload.options.includes("skip"));
}

export function EscalationCenter({ payload, onAction }: EscalationCenterProps) {
  const [guidance, setGuidance] = useState("");
  const [showEdit, setShowEdit] = useState(false);
  const editRef = useRef<HTMLTextAreaElement>(null);
  const deploy = payload ? isDeploy(payload) : false;

  useEffect(() => {
    if (!payload || deploy) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) return;
      const key = event.key.toLowerCase();
      if (key === "r") onAction("retry");
      if (key === "a") onAction("abort");
      if (key === "e") {
        setShowEdit(true);
        window.setTimeout(() => editRef.current?.focus(), 0);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [deploy, onAction, payload]);

  if (!payload) {
    return (
      <section className="empty-screen escalation-empty">
        <div className="empty-glyph">01</div>
        <span className="eyebrow">Human gate</span>
        <h1>No escalation in flight</h1>
        <p>The center will move here when a milestone needs a decision.</p>
      </section>
    );
  }

  return (
    <section className={`escalation-shell ${deploy ? "deploy-shell" : ""}`} aria-labelledby="escalation-title">
      <div className="escalation-banner">
        <span className="escalation-signal">{deploy ? "DEPLOY GATE" : "HUMAN ESCALATION"}</span>
        <span className="keyboard-hint">{deploy ? "approval required" : "R retry · E edit · A abort"}</span>
      </div>
      <div className="escalation-card">
        <div className="escalation-card-heading">
          <div>
            <span className="eyebrow">Decision required</span>
            <h1 id="escalation-title">{deploy ? "Release the artifact?" : "The factory needs your call."}</h1>
          </div>
          <span className="escalation-badge">{deploy ? "deploy" : "escalated"}</span>
        </div>
        <p className="escalation-question">{payload.question}</p>

        {!deploy && payload.failures && payload.failures.length > 0 && (
          <div className="evidence-block failure-block">
            <div className="evidence-label">Failing assertions</div>
            {payload.failures.map((failure, index) => <code key={`${failure}-${index}`}>{failure}</code>)}
          </div>
        )}

        {!deploy && (
          <div className="evidence-grid">
            <div className="evidence-block">
              <div className="evidence-label">Test output</div>
              <pre>{payload.test_output || "No captured test output."}</pre>
            </div>
            <div className="evidence-block">
              <div className="evidence-label">Context diff</div>
              <pre>{payload.context_diff || "No uncommitted diff available."}</pre>
            </div>
          </div>
        )}

        {showEdit && !deploy && (
          <div className="edit-guidance">
            <label htmlFor="human-guidance">Direction for the next attempt</label>
            <textarea
              id="human-guidance"
              ref={editRef}
              value={guidance}
              onChange={event => setGuidance(event.target.value)}
              placeholder="Tell the planner what to change..."
              rows={4}
            />
          </div>
        )}

        <div className="escalation-actions">
          {deploy ? (
            <>
              <button className="button button-primary" onClick={() => onAction("deploy")}>Approve deploy <kbd>Enter</kbd></button>
              <button className="button button-quiet" onClick={() => onAction("skip")}>Skip <kbd>Esc</kbd></button>
            </>
          ) : showEdit ? (
            <>
              <button className="button button-primary" onClick={() => onAction({ action: "edit", guidance })}>Send direction <kbd>Enter</kbd></button>
              <button className="button button-quiet" onClick={() => setShowEdit(false)}>Cancel <kbd>Esc</kbd></button>
            </>
          ) : (
            <>
              <button className="button button-primary" onClick={() => onAction("retry")}>Retry milestone <kbd>R</kbd></button>
              <button className="button button-secondary" onClick={() => setShowEdit(true)}>Edit direction <kbd>E</kbd></button>
              <button className="button button-danger" onClick={() => onAction("abort")}>Abort run <kbd>A</kbd></button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
