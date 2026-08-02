import { useMemo } from "react";
import type { FileTreeEntry } from "../types";

interface FileTreeProps {
  fileTree: FileTreeEntry[];
}

interface TreeNode {
  name: string;
  path: string;
  status?: string;
  children: Map<string, TreeNode>;
}

function buildTree(entries: FileTreeEntry[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map() };

  for (const entry of entries) {
    const parts = entry.path.split("/");
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isFile = i === parts.length - 1;
      const fullPath = parts.slice(0, i + 1).join("/");

      if (!current.children.has(part)) {
        current.children.set(part, {
          name: part,
          path: fullPath,
          status: isFile ? entry.status : undefined,
          children: new Map(),
        });
      }

      current = current.children.get(part)!;
      if (isFile) {
        current.status = entry.status;
      }
    }
  }

  return root;
}

const STATUS_CLASS: Record<string, string> = {
  created: "ft-created",
  modified: "ft-modified",
  existing: "ft-existing",
};

function TreeRow({ node, depth }: { node: TreeNode; depth: number }) {
  const isDir = node.children.size > 0;
  const indent = depth * 16;

  if (depth === 0) {
    return (
      <>
        {[...node.children.values()].map(child => (
          <TreeRow key={child.path} node={child} depth={depth + 1} />
        ))}
      </>
    );
  }

  return (
    <>
      <div
        className={`ft-row ${isDir ? "ft-dir" : ""} ${node.status ? STATUS_CLASS[node.status] ?? "" : ""}`}
        style={{ paddingLeft: indent }}
      >
        <span className="ft-name">{isDir ? `${node.name}/` : node.name}</span>
      </div>
      {isDir &&
        [...node.children.values()].map(child => (
          <TreeRow key={child.path} node={child} depth={depth + 1} />
        ))}
    </>
  );
}

export function FileTree({ fileTree }: FileTreeProps) {
  const tree = useMemo(() => buildTree(fileTree), [fileTree]);

  const counts = useMemo(() => {
    let total = 0;
    let created = 0;
    let modified = 0;
    for (const f of fileTree) {
      total++;
      if (f.status === "created") created++;
      else if (f.status === "modified") modified++;
    }
    return { total, created, modified };
  }, [fileTree]);

  return (
    <div className="file-tree-panel">
      <div className="panel-header">
        Files
        {fileTree.length > 0 && (
          <span className="ft-badge">
            {counts.total} files{counts.created > 0 && ` · ${counts.created} new`}{counts.modified > 0 && ` · ${counts.modified} modified`}
          </span>
        )}
      </div>

      <div className="file-tree">
        {fileTree.length === 0 && (
          <div className="ft-empty">No files yet</div>
        )}
        <TreeRow node={tree} depth={0} />
      </div>
    </div>
  );
}
