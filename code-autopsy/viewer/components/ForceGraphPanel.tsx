"use client";

import { forceCollide } from "d3-force";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef } from "react";
import { GraphEdge, GraphNode } from "../lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  searchText: string;
  edgeType: string;
  includeCalls: boolean;
  maxEdges: number;
  graphLevel: "service" | "package" | "file";
  drillPrefix: string | null;
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

const modulePathForNode = (node: GraphNode): string | null => {
  if (node.type !== "module") return null;
  if (node.id.startsWith("file:")) return node.id.slice(5);
  if (node.label.includes("/")) return node.label;
  return null;
};

const prefixAtDepth = (path: string, depth: number): string => {
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= depth) return path;
  return parts.slice(0, depth).join("/");
};

const resolveGroupNodeId = (path: string, level: "service" | "package" | "file"): string => {
  if (level === "file") return `file:${path}`;
  const depth = level === "service" ? 1 : 2;
  return `group:${prefixAtDepth(path, depth)}`;
};

const resolveGroupNodeLabel = (nodeId: string): string => {
  if (nodeId.startsWith("group:")) return nodeId.slice(6);
  if (nodeId.startsWith("file:")) return nodeId.slice(5);
  return nodeId;
};

export default function ForceGraphPanel({
  nodes,
  edges,
  searchText,
  edgeType,
  includeCalls,
  maxEdges,
  graphLevel,
  drillPrefix,
  focusSelection,
  selectedNodeId,
  onNodeSelect
}: Props) {
  const fgRef = useRef<any>(null);
  const normalized = searchText.trim().toLowerCase();

  const transformed = useMemo(() => {
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const scopedNodes = nodes.filter((node) => {
      if (node.type !== "module") return true;
      const path = modulePathForNode(node);
      if (!path) return false;
      if (!drillPrefix) return true;
      return path.startsWith(drillPrefix);
    });
    const scopedNodeIds = new Set(scopedNodes.map((node) => node.id));

    const scopedEdges = edges.filter((edge) => {
      const fromNode = nodeById.get(edge.from);
      const toNode = nodeById.get(edge.to);
      const fromInScope = scopedNodeIds.has(edge.from);
      const toInScope = scopedNodeIds.has(edge.to);
      if ((fromNode?.type === "module" || toNode?.type === "module") && !fromInScope && !toInScope) {
        return false;
      }
      if (fromNode?.type === "module" && !fromInScope) return false;
      if (toNode?.type === "module" && !toInScope) return false;
      return true;
    });

    const aggregatedNodes = new Map<string, GraphNode>();
    const nodeMapToGroup = new Map<string, string>();

    for (const node of scopedNodes) {
      if (node.type !== "module") {
        aggregatedNodes.set(node.id, node);
        nodeMapToGroup.set(node.id, node.id);
        continue;
      }
      const path = modulePathForNode(node);
      if (!path) continue;
      const groupId = resolveGroupNodeId(path, graphLevel);
      nodeMapToGroup.set(node.id, groupId);
      const existing = aggregatedNodes.get(groupId);
      if (!existing) {
        aggregatedNodes.set(groupId, {
          ...node,
          id: groupId,
          label: resolveGroupNodeLabel(groupId),
          criticality: node.criticality || 0,
        });
      } else {
        aggregatedNodes.set(groupId, {
          ...existing,
          criticality: Math.max(existing.criticality || 0, node.criticality || 0),
        });
      }
    }

    const aggregatedEdges = new Map<string, GraphEdge>();
    for (const edge of scopedEdges) {
      const src = nodeMapToGroup.get(edge.from) || edge.from;
      const dst = nodeMapToGroup.get(edge.to) || edge.to;
      if (!aggregatedNodes.has(src) || !aggregatedNodes.has(dst)) continue;
      if (src === dst) continue;
      const key = `${src}|${dst}|${edge.type}|${edge.confidence || ""}`;
      const existing = aggregatedEdges.get(key);
      if (!existing) {
        aggregatedEdges.set(key, {
          ...edge,
          from: src,
          to: dst,
          weight: 1,
        });
      } else {
        aggregatedEdges.set(key, {
          ...existing,
          weight: (existing.weight || 1) + 1,
        });
      }
    }

    return {
      nodes: [...aggregatedNodes.values()],
      edges: [...aggregatedEdges.values()],
    };
  }, [nodes, edges, graphLevel, drillPrefix]);

  const graphData = useMemo(() => {
    const nodeById = new Map(transformed.nodes.map((node) => [node.id, node]));
    const confidenceWeight = (confidence?: string): number => {
      if (confidence === "high") return 3;
      if (confidence === "medium") return 2;
      return 1;
    };
    const edgeTypeWeight = (type: string): number => {
      if (type === "trust_boundary_crossing") return 1.4;
      if (type === "depends_on") return 1.2;
      if (type === "imports") return 1;
      if (type === "calls") return 0.8;
      return 1;
    };

    let filteredEdges = transformed.edges.filter((edge) => edgeType === "all" || edge.type === edgeType);
    if (!includeCalls && edgeType !== "calls") {
      filteredEdges = filteredEdges.filter((edge) => edge.type !== "calls");
    }
    if (focusSelection && selectedNodeId) {
      filteredEdges = filteredEdges.filter((edge) => edge.from === selectedNodeId || edge.to === selectedNodeId);
    }

    filteredEdges = [...filteredEdges]
      .sort((left, right) => {
        const leftNodeA = nodeById.get(left.from);
        const leftNodeB = nodeById.get(left.to);
        const rightNodeA = nodeById.get(right.from);
        const rightNodeB = nodeById.get(right.to);
        const leftScore =
          confidenceWeight(left.confidence) * edgeTypeWeight(left.type) +
          (leftNodeA?.criticality || 0) +
          (leftNodeB?.criticality || 0);
        const rightScore =
          confidenceWeight(right.confidence) * edgeTypeWeight(right.type) +
          (rightNodeA?.criticality || 0) +
          (rightNodeB?.criticality || 0);
        return rightScore - leftScore;
      })
      .slice(0, Math.max(40, maxEdges));

    const allowedNodes = new Set<string>();

    for (const edge of filteredEdges) {
      allowedNodes.add(edge.from);
      allowedNodes.add(edge.to);
    }

    let filteredNodes = transformed.nodes.filter((node) => allowedNodes.has(node.id));
    if (focusSelection && selectedNodeId) {
      const selectedNode = transformed.nodes.find((node) => node.id === selectedNodeId);
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
  }, [transformed.nodes, transformed.edges, edgeType, normalized, includeCalls, maxEdges, focusSelection, selectedNodeId]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;

    const nodeCount = graphData.nodes.length;
    const linkCount = graphData.links.length;
    const density = linkCount / Math.max(nodeCount, 1);
    const chargeStrength = -Math.min(260, 70 + nodeCount * 0.24 + density * 12);
    const linkDistance = Math.min(130, 72 + Math.sqrt(nodeCount) * 1.8 + density * 4);
    const linkStrength = Math.max(0.25, Math.min(0.75, 0.7 - density * 0.08));

    fg.d3Force("charge")?.strength(chargeStrength);
    fg.d3Force("link")?.distance(linkDistance).strength(linkStrength);
    fg.d3Force(
      "collision",
      forceCollide((node: any) => {
        const label = compressLabel(node.label || node.id || "");
        return 8 + Math.min(8, label.length * 0.22);
      })
        .strength(0.95)
        .iterations(nodeCount > 400 ? 2 : 1)
    );
    fg.d3ReheatSimulation();
  }, [graphData.nodes.length, graphData.links.length, focusSelection, edgeType, normalized, includeCalls, maxEdges]);

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
        const showLabel = globalScale >= 1.15 || isSelected || isNeighbor || node.criticality >= 0.75;
        ctx.fillStyle = isSelected ? "#1d4ed8" : baseColor;
        ctx.beginPath();
        ctx.arc(node.x, node.y, isSelected ? 7 : isNeighbor ? 5.3 : 4.5, 0, 2 * Math.PI, false);
        ctx.fill();

        if (showLabel) {
          ctx.lineWidth = 3 / globalScale;
          ctx.strokeStyle = "rgba(248, 250, 252, 0.96)";
          ctx.strokeText(label, node.x + 8, node.y + 1.5);
          ctx.fillStyle = isSelected ? "#1e293b" : "#0f172a";
          ctx.fillText(label, node.x + 8, node.y + 1.5);
        }
      }}
      linkDirectionalArrowLength={3.5}
      linkDirectionalArrowRelPos={1}
      linkDirectionalParticles={(link: any) => (link.type === "trust_boundary_crossing" ? 1 : 0)}
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
      d3AlphaDecay={0.02}
      d3VelocityDecay={0.28}
      minZoom={0.52}
      maxZoom={4}
      cooldownTicks={260}
    />
  );
}
