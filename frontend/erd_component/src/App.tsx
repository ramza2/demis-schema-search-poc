import { useEffect, useMemo, useState } from "react";
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  getSmoothStepPath,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ELK from "elkjs/lib/elk.bundled.js";
import {
  ComponentProps,
  Streamlit,
  withStreamlitConnection,
} from "streamlit-component-lib";

const elk = new ELK();
const NODE_WIDTH = 250;
const NODE_HEIGHT = 92;

type GraphNode = {
  id: number;
  table_key: string;
  schema_name: string;
  table_name: string;
  table_comment?: string | null;
  categories?: Array<{ id: number; name: string }>;
};

type GraphEdge = {
  id: number;
  constraint: string;
  relation_type: string;
  source_id: number;
  target_id: number;
  source_table_key: string;
  target_table_key: string;
  column_mapping?: Array<{ source: string; target: string }>;
};

type GraphArgs = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId?: number | null;
  distances?: Record<string, number>;
  mode?: string;
  showEdgeLabels?: boolean;
  frameHeight?: number;
};

type EdgePoint = { x: number; y: number };

function nodeTone(distance: number | null | undefined, hasFocus: boolean, selected: boolean) {
  if (selected || distance === 0) return "selected";
  if (distance === 1) return "hop1";
  if (distance === 2) return "hop2";
  if (hasFocus) return "dimmed";
  return "normal";
}

function TableNode(props: any) {
  const data = props.data as any;
  const tone = nodeTone(data.distance, data.hasFocus, Boolean(props.selected));
  const categories = (data.categories || []).map((item: any) => item.name).join(", ");
  return (
    <div className={`erd-node erd-node-${tone}`} title={data.table_key}>
      <Handle type="target" position={Position.Left} className="erd-handle" />
      <div className="erd-schema">{data.schema_name}</div>
      <div className="erd-table">{data.table_name}</div>
      <div className="erd-comment">{data.table_comment || "DB COMMENT 없음"}</div>
      {categories ? <div className="erd-category">{categories}</div> : null}
      <Handle type="source" position={Position.Right} className="erd-handle" />
    </div>
  );
}

function polylineMidpoint(points: EdgePoint[]) {
  if (!points.length) return { x: 0, y: 0 };
  if (points.length === 1) return points[0];
  const lengths: number[] = [];
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    const dx = points[i].x - points[i - 1].x;
    const dy = points[i].y - points[i - 1].y;
    const length = Math.sqrt(dx * dx + dy * dy);
    lengths.push(length);
    total += length;
  }
  let remaining = total / 2;
  for (let i = 1; i < points.length; i += 1) {
    const length = lengths[i - 1];
    if (remaining <= length && length > 0) {
      const ratio = remaining / length;
      return {
        x: points[i - 1].x + (points[i].x - points[i - 1].x) * ratio,
        y: points[i - 1].y + (points[i].y - points[i - 1].y) * ratio,
      };
    }
    remaining -= length;
  }
  return points[points.length - 1];
}

function OrthogonalEdge(props: any) {
  const points = (props.data?.points || []) as EdgePoint[];
  let path = "";
  if (points.length >= 2) {
    path = points
      .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
      .join(" ");
  } else {
    [path] = getSmoothStepPath({
      sourceX: props.sourceX,
      sourceY: props.sourceY,
      targetX: props.targetX,
      targetY: props.targetY,
      sourcePosition: props.sourcePosition,
      targetPosition: props.targetPosition,
    });
  }
  const midpoint = polylineMidpoint(points);
  const faded = Boolean(props.data?.faded);
  const highlighted = Boolean(props.data?.highlighted);
  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={props.markerEnd}
        style={{
          stroke: highlighted ? "#2563eb" : "#94a3b8",
          strokeWidth: highlighted ? 2.4 : 1.5,
          opacity: faded ? 0.22 : 0.9,
        }}
      />
      {props.data?.showLabel && points.length >= 2 ? (
        <EdgeLabelRenderer>
          <div
            className="erd-edge-label nodrag nopan"
            style={{
              transform: `translate(-50%, -50%) translate(${midpoint.x}px,${midpoint.y}px)`,
              opacity: faded ? 0.25 : 1,
            }}
          >
            {props.data.label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

const nodeTypes = { table: TableNode };
const edgeTypes = { orthogonal: OrthogonalEdge };

function relationDegree(nodes: GraphNode[], edges: GraphEdge[]) {
  const degree = new Map<number, number>();
  nodes.forEach((node) => degree.set(node.id, 0));
  edges.forEach((edge) => {
    degree.set(edge.source_id, (degree.get(edge.source_id) || 0) + 1);
    degree.set(edge.target_id, (degree.get(edge.target_id) || 0) + 1);
  });
  return degree;
}

async function layoutGraph(args: GraphArgs) {
  const distances = args.distances || {};
  const hasFocus = args.selectedId !== null && args.selectedId !== undefined;
  const degree = relationDegree(args.nodes || [], args.edges || []);
  const orderedNodes = [...(args.nodes || [])].sort((left, right) => {
    const degreeDiff = (degree.get(right.id) || 0) - (degree.get(left.id) || 0);
    if (degreeDiff !== 0) return degreeDiff;
    return left.table_name.localeCompare(right.table_name);
  });

  const graph: any = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.spacing.nodeNode": "72",
      "elk.layered.spacing.nodeNodeBetweenLayers": "120",
      "elk.layered.spacing.edgeNodeBetweenLayers": "48",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      "elk.padding": "[top=45,left=45,bottom=45,right=45]",
    },
    children: orderedNodes.map((node) => ({
      id: String(node.id),
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    })),
    edges: (args.edges || []).map((edge) => ({
      id: `edge-${edge.id}`,
      sources: [String(edge.source_id)],
      targets: [String(edge.target_id)],
    })),
  };

  const result: any = await elk.layout(graph);
  const layoutNodeById = new Map<string, any>(
    (result.children || []).map((node: any) => [String(node.id), node]),
  );
  const originalNodeById = new Map<number, GraphNode>(
    (args.nodes || []).map((node) => [node.id, node]),
  );

  const flowNodes = (args.nodes || []).map((node) => {
    const layoutNode = layoutNodeById.get(String(node.id));
    return {
      id: String(node.id),
      type: "table",
      position: { x: layoutNode?.x || 0, y: layoutNode?.y || 0 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: { width: NODE_WIDTH, height: NODE_HEIGHT },
      data: {
        ...node,
        degree: degree.get(node.id) || 0,
        distance: distances[String(node.id)],
        hasFocus,
      },
    };
  });

  const originalEdgeByKey = new Map<string, GraphEdge>(
    (args.edges || []).map((edge) => [`edge-${edge.id}`, edge]),
  );
  const flowEdges = (result.edges || []).map((edge: any) => {
    const original = originalEdgeByKey.get(String(edge.id));
    const section = edge.sections?.[0];
    const points: EdgePoint[] = section
      ? [section.startPoint, ...(section.bendPoints || []), section.endPoint]
      : [];
    const sourceDistance = original ? distances[String(original.source_id)] : undefined;
    const targetDistance = original ? distances[String(original.target_id)] : undefined;
    const relevant = !hasFocus || sourceDistance !== undefined || targetDistance !== undefined;
    const highlighted =
      hasFocus &&
      (sourceDistance === 0 || targetDistance === 0 || sourceDistance === 1 || targetDistance === 1);
    return {
      id: String(edge.id),
      type: "orthogonal",
      source: String(original?.source_id ?? edge.sources?.[0] ?? ""),
      target: String(original?.target_id ?? edge.targets?.[0] ?? ""),
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      data: {
        label: original?.constraint || "FK",
        points,
        showLabel: Boolean(args.showEdgeLabels),
        faded: !relevant,
        highlighted,
      },
    };
  });

  return { flowNodes, flowEdges, originalNodeById };
}

function GraphCanvas({ args }: { args: GraphArgs }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { fitView } = useReactFlow();

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    layoutGraph(args)
      .then(({ flowNodes, flowEdges }) => {
        if (!active) return;
        setNodes(flowNodes);
        setEdges(flowEdges);
        setLoading(false);
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            fitView({ padding: 0.16, duration: 250, maxZoom: 1.15 });
          });
        });
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setLoading(false);
        setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      active = false;
    };
  }, [args, fitView, setEdges, setNodes]);

  const onNodeClick = (_event: unknown, node: any) => {
    Streamlit.setComponentValue({
      table_id: Number(node.id),
      table_key: node.data?.table_key,
    });
  };

  const minimapColor = (node: any) => {
    const distance = node.data?.distance;
    if (distance === 0) return "#16a34a";
    if (distance === 1) return "#2563eb";
    if (distance === 2) return "#64748b";
    return "#cbd5e1";
  };

  if (error) {
    return <div className="erd-status erd-error">ELK layout 실패: {error}</div>;
  }

  return (
    <div className="erd-canvas">
      {loading ? <div className="erd-status">ELK 자동 배치 계산 중…</div> : null}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodesConnectable={false}
        elementsSelectable
        minZoom={0.08}
        maxZoom={2.2}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <MiniMap pannable zoomable nodeColor={minimapColor} maskColor="rgba(248,250,252,0.72)" />
        <Controls showInteractive={false} />
        <Background gap={18} size={1} color="#e2e8f0" />
      </ReactFlow>
    </div>
  );
}

function ErdComponent(props: ComponentProps) {
  const args = (props.args || {}) as GraphArgs;
  const frameHeight = Math.max(520, Number(args.frameHeight || 760));
  const safeArgs = useMemo(
    () => ({
      ...args,
      nodes: args.nodes || [],
      edges: args.edges || [],
      distances: args.distances || {},
    }),
    [args],
  );

  useEffect(() => {
    Streamlit.setFrameHeight(frameHeight);
  }, [frameHeight]);

  return (
    <div className="erd-root" style={{ height: `${frameHeight - 6}px` }}>
      <div className="erd-toolbar">
        <span><b>React Flow</b> + ELK layered / orthogonal</span>
        <span>Drag · Zoom · Pan · MiniMap</span>
        {args.mode === "full" ? <span>전체 ERD: FK label 숨김</span> : null}
      </div>
      <GraphCanvas args={safeArgs} />
    </div>
  );
}

export default withStreamlitConnection(ErdComponent);
