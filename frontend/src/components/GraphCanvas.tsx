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
  let state = "dormant";
  if (data?.active) {
    cls += " active";
    state = "bonded";
  } else if (data?.result === "success") {
    cls += " success";
    state = "verified";
  } else if (data?.result === "error") {
    cls += " error";
    state = "severed";
  }

  return (
    <div className={cls} data-testid={`hive-node-${id}`}>
      <Handle type="target" position={Position.Top} style={{ visibility: "hidden" }} />
      <div className="node-label">{(data?.label as string) ?? id}</div>
      {data?.liveMsg != null && (
        <div className="node-live-status">{String(data.liveMsg)}</div>
      )}
      <div className="node-state">{state}</div>
      <Handle type="source" position={Position.Bottom} style={{ visibility: "hidden" }} />
    </div>
  );
}

const nodeTypes = { agentNode: AgentNode };

interface GraphCanvasProps {
  activeNode: string | null;
  completedNodes: Record<string, NodeResult>;
  status: RunStatus;
  liveStatus: Record<string, string>;
}

export function GraphCanvas({ activeNode, completedNodes, status, liveStatus }: GraphCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(GRAPH_NODES);
  const [edges, setEdges] = useEdgesState(GRAPH_EDGES);

  useEffect(() => {
    const live = status === "running";
    setEdges(GRAPH_EDGES.map(edge => ({
      ...edge,
      animated: edge.animated || (live && edge.source === activeNode),
      className:
        edge.target === "escalation" || edge.target === "cleanup" || edge.source === "escalation"
          ? "edge-fail"
          : edge.target === "advance" || edge.target === "deploy_gate"
            ? "edge-pass"
            : undefined,
    })));
    setNodes(prev =>
      prev.map(n => ({
        ...n,
        type: "agentNode" as const,
        data: {
          ...n.data,
          active: n.id === activeNode && live,
          result: completedNodes[n.id] ?? null,
          liveMsg: liveStatus[n.id] ?? null,
        },
      }))
    );
  }, [activeNode, completedNodes, status, liveStatus, setEdges, setNodes]);

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
