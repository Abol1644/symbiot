import type { InterruptPayload } from "../types";

interface InterruptModalProps {
  payload: InterruptPayload;
  onResume: (choice: string) => void;
}

function isDeploy(payload: InterruptPayload): boolean {
  return payload.options.includes("deploy") && payload.options.includes("skip");
}

export function InterruptModal({ payload, onResume }: InterruptModalProps) {
  const deployMode = isDeploy(payload);

  return (
    <div className="interrupt-overlay">
      <div className={`interrupt-card${deployMode ? " deploy" : ""}`}>
        <h2>{deployMode ? "Deploy" : "Human-in-the-Loop"}</h2>
        <div className="question">{payload.question}</div>

        {!deployMode && payload.failures && payload.failures.length > 0 && (
          <ul className="failures-list">
            {payload.failures.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        )}

        <div className="interrupt-actions">
          {deployMode ? (
            <>
              <button className="btn btn-run" onClick={() => onResume("deploy")}>
                Deploy image
              </button>
              <button className="btn" onClick={() => onResume("skip")}>
                Skip
              </button>
            </>
          ) : (
            <>
              <button className="btn" onClick={() => onResume("retry (reset attempts, +3 more)")}>
                Retry (+3 attempts)
              </button>
              <button className="btn btn-abort" onClick={() => onResume("abort")}>
                Abort
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
