import type { Node, Edge } from "@xyflow/react";

export const GRAPH_NODES: Node[] = [
  { id: "validator",   position: { x: 300, y: 0 },   data: { label: "Validator" } },
  { id: "base",        position: { x: 300, y: 100 },  data: { label: "Base" } },
  { id: "planner",     position: { x: 300, y: 200 },  data: { label: "Planner" } },
  { id: "programmer",  position: { x: 300, y: 300 },  data: { label: "Programmer" } },
  { id: "tester",      position: { x: 300, y: 400 },  data: { label: "Tester" } },
  { id: "escalation",  position: { x: 550, y: 400 },  data: { label: "Escalation" } },
  { id: "advance",     position: { x: 50,  y: 400 },  data: { label: "Advance" } },
  { id: "deploy_gate", position: { x: 50,  y: 520 },  data: { label: "Deploy Gate" } },
  { id: "deployer",    position: { x: 50,  y: 620 },  data: { label: "Deployer" } },
  { id: "cleanup",     position: { x: 300, y: 640 },  data: { label: "Cleanup" } },
];

export const GRAPH_EDGES: Edge[] = [
  { id: "e1", source: "validator",   target: "base" },
  { id: "e2", source: "base",        target: "planner" },
  { id: "e3", source: "planner",     target: "programmer" },
  { id: "e4", source: "programmer",  target: "tester" },
  { id: "e5", source: "tester",      target: "advance",     label: "pass" },
  { id: "e6", source: "tester",      target: "planner",     label: "retry", animated: true },
  { id: "e7", source: "tester",      target: "escalation",  label: "fail" },
  { id: "e8", source: "escalation",  target: "planner",     label: "retry", animated: true },
  { id: "e9", source: "escalation",  target: "cleanup",     label: "abort" },
  { id: "e10", source: "advance",    target: "planner",     label: "next", animated: true },
  { id: "e11", source: "advance",    target: "deploy_gate", label: "done" },
  { id: "e12", source: "deploy_gate",target: "deployer",    label: "approve" },
  { id: "e13", source: "deploy_gate",target: "cleanup",     label: "skip" },
  { id: "e14", source: "deployer",   target: "cleanup" },
];
