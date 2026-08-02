import { useState, useCallback } from "react";
import { sidecar, type ProjectInfo, type BrowseResult } from "../api/sidecar";

interface ProjectLoaderProps {
  onLoadSpec: (spec: string) => void;
  onSelectSource: (sourcePath: string | null) => void;
  sourcePath: string | null;
}

export function ProjectLoader({ onLoadSpec, onSelectSource, sourcePath }: ProjectLoaderProps) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [browsePath, setBrowsePath] = useState("");
  const [browseResult, setBrowseResult] = useState<BrowseResult | null>(null);
  const [loading, setLoading] = useState(false);

  const doOpen = useCallback(async () => {
    setOpen(true);
    try {
      setProjects(await sidecar.listProjects());
    } catch {
      setProjects([]);
    }
  }, []);

  const loadProjectSpec = async (name: string) => {
    try {
      const spec = await sidecar.getSpec(name);
      onLoadSpec(spec);
      setOpen(false);
    } catch {
      // ignore
    }
  };

  const doBrowse = async (path: string) => {
    setBrowsePath(path);
    setLoading(true);
    try {
      setBrowseResult(await sidecar.browse(path));
    } catch {
      setBrowseResult(null);
    }
    setLoading(false);
  };

  const parentDir = () => {
    if (!browseResult) return;
    const p = browseResult.path.split("/").slice(0, -1).join("/") || "/";
    doBrowse(p);
  };

  const importPath = (p: string) => {
    onSelectSource(p);
    setOpen(false);
  };

  return (
    <>
      <button className="btn" onClick={doOpen}>Load spec</button>

      {open && (
        <div className="drawer-overlay" onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
          <div className="drawer">
            <div className="drawer-header">
              <span className="drawer-title">Load Project</span>
              <button className="btn" onClick={() => setOpen(false)}>Close</button>
            </div>

            <div className="drawer-section">
              <div className="drawer-section-title">Saved Projects</div>
              <div className="project-cards">
                {projects.map(p => (
                  <div key={p.name} className="project-card" onClick={() => loadProjectSpec(p.name)}>
                    <div className="project-card-name">{p.name}</div>
                    <div className="project-card-meta">
                      {p.has_spec && <span className="chip chip-spec">spec</span>}
                    </div>
                  </div>
                ))}
                {projects.length === 0 && (
                  <div className="text-dim" style={{ fontSize: 12 }}>No projects found in projects/</div>
                )}
              </div>
            </div>

            <div className="drawer-section">
              <div className="drawer-section-title">Import from Disk</div>
              <div className="import-row">
                <input
                  className="import-input"
                  placeholder="/home/user/my-project"
                  value={browsePath}
                  onChange={(e) => setBrowsePath(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") doBrowse(browsePath); }}
                />
                <button className="btn" onClick={() => doBrowse(browsePath)} disabled={loading}>
                  Browse
                </button>
              </div>

              {sourcePath && (
                <div className="source-chip">
                  <span>Source: {sourcePath}</span>
                  <button className="chip-close" onClick={() => onSelectSource(null)}>x</button>
                </div>
              )}

              {browseResult && (
                <div className="browse-list">
                  <div className="browse-crumb" onClick={parentDir}>
                    &uarr; {browseResult.path}
                  </div>
                  {browseResult.dirs.map(d => (
                    <div
                      key={d}
                      className="browse-entry browse-dir"
                      onClick={() => doBrowse(`${browseResult.path}/${d}`)}
                    >
                      {d}/
                    </div>
                  ))}
                  {browseResult.files.map(f => (
                    <div key={f} className="browse-entry browse-file">{f}</div>
                  ))}
                  {browseResult.dirs.length === 0 && browseResult.files.length === 0 && (
                    <div className="text-dim" style={{ padding: 8 }}>Empty directory</div>
                  )}
                  <button
                    className="btn btn-run"
                    style={{ marginTop: 8 }}
                    onClick={() => importPath(browseResult.path)}
                  >
                    Import &quot;{browseResult.path.split("/").pop() || browseResult.path}&quot;
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
