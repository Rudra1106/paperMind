import { useMemo } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  Handle,
  Position,
  MarkerType
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';
import './ConceptGraph.css';

// ── Custom Node ──────────────────────────────────────────────────────────────
function ConceptNode({ data }) {
  const { label, priority } = data;
  
  let glowColor = 'rgba(255,255,255,0.2)';
  if (priority === 'critical') glowColor = 'var(--danger)';
  else if (priority === 'high') glowColor = 'var(--warning)';
  else if (priority === 'medium') glowColor = 'var(--indigo-400)';
  else if (priority === 'almost_there') glowColor = 'var(--success)';

  return (
    <div className="concept-node" style={{ '--glow-color': glowColor }}>
      <Handle type="target" position={Position.Top} className="concept-handle" />
      <div className="concept-node-label">{label}</div>
      <Handle type="source" position={Position.Bottom} className="concept-handle" />
    </div>
  );
}

const nodeTypes = {
  concept: ConceptNode,
};

// ── Layout Algorithm (Dagre) ─────────────────────────────────────────────────
const getLayoutedElements = (nodes, edges, direction = 'TB') => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  // Match the width/height defined in CSS for the nodes
  const nodeWidth = 200;
  const nodeHeight = 44;

  dagreGraph.setGraph({ rankdir: direction, ranksep: 60, nodesep: 40 });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      targetPosition: 'top',
      sourcePosition: 'bottom',
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

// ── Main Graph Component ─────────────────────────────────────────────────────
export function ConceptGraph({ roadmap }) {
  const { initialNodes, initialEdges } = useMemo(() => {
    if (!roadmap || roadmap.length === 0) return { initialNodes: [], initialEdges: [] };

    const nodeIds = new Set(roadmap.map(c => c.canonical_name));

    const nodes = roadmap.map((c) => ({
      id: c.canonical_name,
      type: 'concept',
      data: {
        label: c.display_name,
        priority: c.priority,
        confidence: c.confidence
      },
      position: { x: 0, y: 0 },
    }));

    const edges = [];
    roadmap.forEach((c) => {
      (c.requires || []).forEach((req) => {
        if (nodeIds.has(req)) {
          edges.push({
            id: `e-${req}-${c.canonical_name}`,
            source: req,
            target: c.canonical_name,
            type: 'smoothstep',
            animated: true,
            style: { stroke: 'rgba(255,255,255,0.4)', strokeWidth: 2 },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: 'rgba(255,255,255,0.4)',
            },
          });
        }
      });
    });

    return getLayoutedElements(nodes, edges, 'TB');
  }, [roadmap]);

  if (initialNodes.length === 0) {
    return <div className="empty-graph">No concepts to display.</div>;
  }

  return (
    <div className="concept-graph-wrapper">
      <ReactFlow
        nodes={initialNodes}
        edges={initialEdges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#fff" gap={24} size={1} opacity={0.05} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
