import { useState, useEffect, useCallback, useRef } from "react";
import { sidecar, type GitCommit } from "../api/sidecar";

interface GitPanelProps {
  workspaceName: string | null;
  onRefreshFileTree: () => void;
}

function relativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = Date.now();
  const diff = now - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function GitPanel({ workspaceName, onRefreshFileTree }: GitPanelProps) {
  const [commits, setCommits] = useState<GitCommit[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [diffText, setDiffText] = useState<string>("");
  const [uncommitted, setUncommitted] = useState(0);
  const [rollbackHash, setRollbackHash] = useState<string | null>(null);
  const [holdProgress, setHoldProgress] = useState(0);

  const fetchedRef = useRef(false);

  const fetchData = useCallback(async () => {
    if (!workspaceName) return;
    try {
      const [log, status] = await Promise.all([
        sidecar.gitLog(workspaceName),
        sidecar.gitStatus(workspaceName),
      ]);
      setCommits(log);
      setUncommitted(status.length);
    } catch {
      // ignore
    }
  }, [workspaceName]);

  useEffect(() => {
    if (workspaceName && !fetchedRef.current) {
      fetchedRef.current = true;
      fetchData();
    }
    if (!workspaceName) {
      fetchedRef.current = false;
    }
  }, [workspaceName, fetchData]);

  const doRollback = useCallback(async (hash: string) => {
    if (!workspaceName) return;
    try {
      await sidecar.gitRollback(workspaceName, hash);
      await fetchData();
      onRefreshFileTree();
    } finally {
      setRollbackHash(null);
      setHoldProgress(0);
    }
  }, [workspaceName, fetchData, onRefreshFileTree]);

  const holdTimerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  useEffect(() => {
    if (!rollbackHash) {
      if (holdTimerRef.current) {
        clearInterval(holdTimerRef.current);
        holdTimerRef.current = undefined;
      }
      return;
    }
    holdTimerRef.current = setInterval(() => {
      setHoldProgress(prev => {
        if (prev >= 100) {
          if (holdTimerRef.current) clearInterval(holdTimerRef.current);
          return 100;
        }
        return prev + 5;
      });
    }, 50);
    return () => { if (holdTimerRef.current) clearInterval(holdTimerRef.current); };
  }, [rollbackHash]);

  useEffect(() => {
    if (holdProgress >= 100 && rollbackHash) {
      doRollback(rollbackHash);
    }
  }, [holdProgress, rollbackHash, doRollback]);

  const loadDiff = async (hash: string) => {
    if (expanded === hash) {
      setExpanded(null);
      return;
    }
    setExpanded(hash);
    setDiffText("");
    try {
      const diff = await sidecar.gitDiff(workspaceName!, hash);
      setDiffText(diff);
    } catch {
      setDiffText("Failed to load diff");
    }
  };

  if (!workspaceName) {
    return (
      <div className="git-panel">
        <div className="panel-header">Git</div>
        <div className="ft-empty">No workspace yet</div>
      </div>
    );
  }

  return (
    <div className="git-panel">
      <div className="panel-header">
        Git
        {commits.length > 0 && (
          <span className="ft-badge">{commits.length} commits</span>
        )}
      </div>

      <div className="git-rail">
        {commits.map((c, i) => (
          <div key={c.hash} className={`git-commit ${i === 0 ? "latest" : ""}`}>
            <div className="git-dot" onClick={() => loadDiff(c.hash)} />
            {i < commits.length - 1 && <div className="git-line" />}
            <div className="git-commit-info">
              <span className="git-hash" onClick={() => loadDiff(c.hash)}>{c.short}</span>
              <span className="git-msg">{c.message}</span>
              <span className="git-time">{relativeTime(c.date)}</span>

              <button
                className="git-rollback-btn"
                onMouseDown={() => setRollbackHash(c.hash)}
                onMouseUp={() => { setRollbackHash(null); setHoldProgress(0); }}
                onMouseLeave={() => { setRollbackHash(null); setHoldProgress(0); }}
                style={
                  rollbackHash === c.hash
                    ? { background: `linear-gradient(to right, var(--error-bg) ${holdProgress}%, transparent ${holdProgress}%)` }
                    : undefined
                }
              >
                {rollbackHash === c.hash ? `Hold... ${Math.round(holdProgress)}%` : "Rollback"}
              </button>

              {expanded === c.hash && (
                <div className="git-diff">
                  {diffText ? (
                    <pre className="git-diff-content">
                      {diffText.split("\n").map((line, li) => {
                        let cls = "";
                        if (line.startsWith("+") && !line.startsWith("+++")) cls = "diff-add";
                        else if (line.startsWith("-") && !line.startsWith("---")) cls = "diff-rem";
                        else if (line.startsWith("@@")) cls = "diff-hunk";
                        return (
                          <div key={li} className={`diff-line ${cls}`}>
                            <span className="diff-ln">{li + 1}</span>
                            {line}
                          </div>
                        );
                      })}
                    </pre>
                  ) : (
                    <div className="diff-loading">Loading diff...</div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {commits.length === 0 && (
          <div className="ft-empty">No commits yet</div>
        )}
      </div>

      {uncommitted > 0 && (
        <div className="git-uncommitted">{uncommitted} uncommitted change{uncommitted !== 1 ? "s" : ""}</div>
      )}
    </div>
  );
}
