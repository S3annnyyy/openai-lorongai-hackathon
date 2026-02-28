"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { GraphEdge, GraphNode } from "../lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  searchText: string;
  edgeType: string;
  selectedNodeId: string | null;
  onNodeSelect: (nodeId: string) => void;
};

const defaultNodeColor = (node: GraphNode): string => {
  if (node.type === "external") {
    return "#64748b";
  }
  if (node.criticality >= 0.75) {
    return "#dc2626";
  }
  if (node.criticality >= 0.5) {
    return "#ea580c";
  }
  if (node.criticality >= 0.3) {
    return "#2563eb";
  }
  return "#0f766e";
};

export default function ForceGraphPanel({
  nodes,
  edges,
  searchText,
  edgeType,
  selectedNodeId,
  onNodeSelect
}: Props) {
  const normalized = searchText.trim().toLowerCase();

  const graphData = useMemo(() => {
    const filteredEdges = edges.filter((edge) => edgeType === "all" || edge.type === edgeType);
    const allowedNodes = new Set<string>();

    for (const edge of filteredEdges) {
      allowedNodes.add(edge.from);
      allowedNodes.add(edge.to);
    }

    let filteredNodes = nodes.filter((node) => allowedNodes.has(node.id));

    if (normalized) {
      filteredNodes = filteredNodes.filter((node) => node.label.toLowerCase().includes(normalized));
      const filteredNodeIds = new Set(filteredNodes.map((node) => node.id));
      return {
        nodes: filteredNodes,
        links: filteredEdges.filter(
          (edge) => filteredNodeIds.has(edge.from) || filteredNodeIds.has(edge.to)
        )
      };
    }

    return { nodes: filteredNodes, links: filteredEdges };
  }, [nodes, edges, edgeType, normalized]);

  return (
    <ForceGraph2D
      graphData={graphData as any}
      nodeLabel={(node: any) => `${node.label}\ncriticality=${node.criticality}`}
      nodeAutoColorBy={undefined}
      nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const label = node.label || node.id;
        const fontSize = 12 / globalScale;
        ctx.font = `${fontSize}px IBM Plex Sans`;
        ctx.fillStyle = defaultNodeColor(node as GraphNode);
        ctx.beginPath();
        ctx.arc(node.x, node.y, selectedNodeId === node.id ? 6 : 4.5, 0, 2 * Math.PI, false);
        ctx.fill();

        ctx.fillStyle = "#0f172a";
        ctx.fillText(label, node.x + 8, node.y + 4);
      }}
      linkDirectionalArrowLength={3.5}
      linkDirectionalArrowRelPos={1}
      linkColor={(link: any) => {
        if (link.type === "trust_boundary_crossing") {
          return "#dc2626";
        }
        if (link.type === "depends_on") {
          return "#475569";
        }
        if (link.type === "calls") {
          return "#2563eb";
        }
        return "#0f766e";
      }}
      linkWidth={(link: any) => (link.confidence === "high" ? 1.8 : 1.2)}
      onNodeClick={(node: any) => onNodeSelect(node.id)}
      cooldownTicks={120}
    />
  );
}
