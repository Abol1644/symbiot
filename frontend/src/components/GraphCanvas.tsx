import { useEffect } from "react";
import {
  ReactFlow,
  useNodesState,
  useEdgesState,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { GRAPH_NODES, GRAPH_EDGES } from "../graphLayout";
import type { RunStatus, NodeResult } from "../types";

function AgentNode({ data, id }: NodeProps) {
  let cls = "node-card";
  if (data?.active) cls += " active";
  else if (data?.result === "success") cls += " success";
  else if (data?.result === "error") cls += " error";

  return (
    <div className={cls}>
      <Handle type="target" position={Position.Top} style={{ visibility: "hidden" }} />
      {data?.label as string ?? id}
      <Handle type="source" position={Position.Bottom} style={{ visibility: "hidden" }} />
    </div>
  );
}

const nodeTypes = { agentNode: AgentNode };

interface GraphCanvasProps {
  activeNode: string | null;
  completedNodes: Record<string, NodeResult>;
  status: RunStatus;
}

export function GraphCanvas({ activeNode, completedNodes, status }: GraphCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(GRAPH_NODES);
  const [edges] = useEdgesState(GRAPH_EDGES);

  useEffect(() => {
    setNodes(prev =>
      prev.map(n => ({
        ...n,
        type: "agentNode" as const,
        data: {
          ...n.data,
          active: n.id === activeNode && status === "running",
          result: completedNodes[n.id] ?? null,
        },
      }))
    );
  }, [activeNode, completedNodes, status, setNodes]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      nodeTypes={nodeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      fitView
      attributionPosition="bottom-left"
    />
  );
}
