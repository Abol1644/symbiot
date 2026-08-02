export interface ProjectInfo {
  name: string;
  has_spec: boolean;
}

export interface BrowseResult {
  path: string;
  dirs: string[];
  files: string[];
  has_git: boolean;
  has_spec: boolean;
}

export interface GitCommit {
  hash: string;
  short: string;
  message: string;
  date: string;
}

export interface GitStatusEntry {
  code: string;
  path: string;
}

export interface FileTreeEntry {
  path: string;
  size: number;
}

const BASE = "/fs";

async function get<T>(url: string): Promise<T> {
  const r = await fetch(`${BASE}${url}`);
  if (!r.ok) throw new Error(`${r.status}: ${r.statusText}`);
  return r.json() as Promise<T>;
}

async function getText(url: string): Promise<string> {
  const r = await fetch(`${BASE}${url}`);
  if (!r.ok) throw new Error(`${r.status}: ${r.statusText}`);
  return r.text();
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status}: ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const sidecar = {
  listProjects: () => get<ProjectInfo[]>("/projects"),
  getSpec: (name: string) => getText(`/projects/${encodeURIComponent(name)}/spec`),
  browse: (path: string) =>
    get<BrowseResult>(`/browse?path=${encodeURIComponent(path)}`),
  workspaceTree: (name: string) =>
    get<FileTreeEntry[]>(`/workspace/${encodeURIComponent(name)}/tree`),
  workspaceFile: (name: string, path: string) =>
    getText(`/workspace/${encodeURIComponent(name)}/file?path=${encodeURIComponent(path)}`),
  gitLog: (name: string) =>
    get<GitCommit[]>(`/workspace/${encodeURIComponent(name)}/git/log`),
  gitDiff: (name: string, commit: string) =>
    getText(`/workspace/${encodeURIComponent(name)}/git/diff?commit=${encodeURIComponent(commit)}`),
  gitStatus: (name: string) =>
    get<GitStatusEntry[]>(`/workspace/${encodeURIComponent(name)}/git/status`),
  gitRollback: (name: string, commit: string) =>
    post<GitCommit[]>(`/workspace/${encodeURIComponent(name)}/git/rollback`, { commit }),
};
