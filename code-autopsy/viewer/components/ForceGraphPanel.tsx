"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef } from "react";
import { GraphEdge, GraphNode } from "../lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  searchText: string;
  edgeType: string;
  focusSelection: boolean;
  selectedNodeId: string | null;
  onNodeSelect: (nodeId: string | null) => void;
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

const compressLabel = (label: string): string => {
  if (label.length <= 28) return label;
  const parts = label.split("/");
  if (parts.length >= 2) {
    return `.../${parts.slice(-2).join("/")}`;
  }
  return `${label.slice(0, 25)}...`;
};

export default function ForceGraphPanel({
  nodes,
  edges,
  searchText,
  edgeType,
  focusSelection,
  selectedNodeId,
  onNodeSelect
}: Props) {
  const fgRef = useRef<any>(null);
  const normalized = searchText.trim().toLowerCase();

  const graphData = useMemo(() => {
    let filteredEdges = edges.filter((edge) => edgeType === "all" || edge.type === edgeType);
    if (focusSelection && selectedNodeId) {
      filteredEdges = filteredEdges.filter((edge) => edge.from === selectedNodeId || edge.to === selectedNodeId);
    }
    const allowedNodes = new Set<string>();

    for (const edge of filteredEdges) {
      allowedNodes.add(edge.from);
      allowedNodes.add(edge.to);
    }

    let filteredNodes = nodes.filter((node) => allowedNodes.has(node.id));
    if (focusSelection && selectedNodeId) {
      const selectedNode = nodes.find((node) => node.id === selectedNodeId);
      if (selectedNode && !filteredNodes.some((node) => node.id === selectedNodeId)) {
        filteredNodes = [...filteredNodes, selectedNode];
      }
    }

    if (normalized) {
      filteredNodes = filteredNodes.filter((node) => node.label.toLowerCase().includes(normalized));
      const filteredNodeIds = new Set(filteredNodes.map((node) => node.id));
      const links = filteredEdges
        .filter((edge) => filteredNodeIds.has(edge.from) || filteredNodeIds.has(edge.to))
        .map((edge) => ({
          ...edge,
          source: edge.from,
          target: edge.to,
        }));
      return {
        nodes: filteredNodes,
        links,
      };
    }

    return {
      nodes: filteredNodes,
      links: filteredEdges.map((edge) => ({
        ...edge,
        source: edge.from,
        target: edge.to,
      })),
    };
  }, [nodes, edges, edgeType, normalized, focusSelection, selectedNodeId]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;

    fg.d3Force("charge")?.strength(-34);
    fg.d3Force("link")?.distance(62).strength(0.95);
    fg.d3Force("collision", null);
    fg.d3ReheatSimulation();
  }, [graphData.nodes.length, graphData.links.length, focusSelection, edgeType, normalized]);

  const neighborIds = useMemo(() => {
    const ids = new Set<string>();
    if (!selectedNodeId) return ids;
    const resolveNodeId = (value: any): string =>
      typeof value === "string" ? value : (value?.id as string) || "";
    for (const link of graphData.links as Array<any>) {
      const sourceId = resolveNodeId(link.source);
      const targetId = resolveNodeId(link.target);
      if (sourceId === selectedNodeId && targetId) ids.add(targetId);
      if (targetId === selectedNodeId && sourceId) ids.add(sourceId);
    }
    return ids;
  }, [graphData.links, selectedNodeId]);

  return (
    <ForceGraph2D
      graphData={graphData as any}
      ref={fgRef}
      linkSource="source"
      linkTarget="target"
      nodeLabel={(node: any) => `${node.label}\ncriticality=${node.criticality}`}
      nodeAutoColorBy={undefined}
      nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const label = compressLabel(node.label || node.id);
        const fontSize = 12 / globalScale;
        ctx.font = `${fontSize}px IBM Plex Sans`;
        ctx.textBaseline = "middle";
        const isSelected = selectedNodeId === node.id;
        const isNeighbor = neighborIds.has(node.id);
        const baseColor = defaultNodeColor(node as GraphNode);
        ctx.fillStyle = isSelected ? "#1d4ed8" : baseColor;
        ctx.beginPath();
        ctx.arc(node.x, node.y, isSelected ? 7 : isNeighbor ? 5.3 : 4.5, 0, 2 * Math.PI, false);
        ctx.fill();

        ctx.lineWidth = 3 / globalScale;
        ctx.strokeStyle = "rgba(248, 250, 252, 0.96)";
        ctx.strokeText(label, node.x + 8, node.y + 1.5);
        ctx.fillStyle = isSelected ? "#1e293b" : "#0f172a";
        ctx.fillText(label, node.x + 8, node.y + 1.5);
      }}
      linkDirectionalArrowLength={3.5}
      linkDirectionalArrowRelPos={1}
      linkDirectionalParticles={1}
      linkDirectionalParticleSpeed={(link: any) => (link.confidence === "high" ? 0.008 : 0.004)}
      linkDirectionalParticleWidth={(link: any) => (link.confidence === "high" ? 2.4 : 1.4)}
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
      linkWidth={(link: any) => {
        if (link.confidence === "high") return 2.2;
        if (link.confidence === "medium") return 1.6;
        return 1.2;
      }}
      onNodeClick={(node: any) => onNodeSelect(node.id)}
      onBackgroundClick={() => onNodeSelect(null)}
      d3AlphaDecay={0.028}
      d3VelocityDecay={0.36}
      minZoom={0.52}
      maxZoom={4}
      cooldownTicks={180}
    />
  );
}
