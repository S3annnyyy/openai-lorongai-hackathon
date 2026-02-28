"use client";

import mermaid from "mermaid";
import { useEffect, useMemo, useState } from "react";

type Props = {
  diagram: string;
  title: string;
  compact?: boolean;
  expanded?: boolean;
  detailLevel?: DetailLevel;
  focusText?: string;
  diagramKind?: DiagramKind;
};

type DetailLevel = "overview" | "full";
type DiagramKind =
  | "architecture_services"
  | "architecture_code"
  | "architecture_iac"
  | "er"
  | "call_graph"
  | "dependencies";

type IconName = "copy" | "download" | "close" | "check";

function Icon({ name }: { name: IconName }) {
  if (name === "copy") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="9" y="9" width="11" height="11" rx="2" />
        <rect x="4" y="4" width="11" height="11" rx="2" />
      </svg>
    );
  }
  if (name === "download") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 4v11M8 11l4 4 4-4M5 20h14" />
      </svg>
    );
  }
  if (name === "close") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m6 6 12 12M18 6 6 18" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m5 12 5 5 9-9" />
    </svg>
  );
}

function IconButton({
  icon,
  label,
  onClick,
  disabled = false
}: {
  icon: IconName;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button className="icon-btn" onClick={onClick} type="button" disabled={disabled} aria-label={label} title={label}>
      <Icon name={icon} />
    </button>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  disabled = false,
  success = false
}: {
  icon: IconName;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  success?: boolean;
}) {
  return (
    <button
      className={`action-btn ${success ? "success" : ""}`}
      onClick={onClick}
      type="button"
      disabled={disabled}
      aria-label={label}
      title={label}
    >
      <Icon name={icon} />
      <span>{label}</span>
    </button>
  );
}

type DiagramScale = "small" | "medium" | "large";

const HOPS_FOR_LEVEL: Record<DetailLevel, number> = {
  overview: 1,
  full: 4
};

const FLOW_EDGE_CAP: Record<DetailLevel, Record<DiagramScale, number>> = {
  overview: { small: 12, medium: 24, large: 40 },
  full: { small: 5000, medium: 5000, large: 5000 }
};

const FLOW_NODE_CAP: Record<DetailLevel, Record<DiagramScale, number>> = {
  overview: { small: 12, medium: 20, large: 36 },
  full: { small: Number.POSITIVE_INFINITY, medium: Number.POSITIVE_INFINITY, large: Number.POSITIVE_INFINITY }
};

const ER_ENTITY_CAP: Record<DetailLevel, Record<DiagramScale, number>> = {
  overview: { small: 6, medium: 10, large: 14 },
  full: { small: 600, medium: 600, large: 600 }
};

const ER_RELATION_CAP: Record<DetailLevel, Record<DiagramScale, number>> = {
  overview: { small: 12, medium: 18, large: 24 },
  full: { small: 5000, medium: 5000, large: 5000 }
};

const DIAGRAM_SCALE_HINT: Partial<Record<DiagramKind, DiagramScale>> = {
  architecture_services: "small",
  architecture_code: "medium",
  architecture_iac: "small",
  er: "medium",
  call_graph: "large",
  dependencies: "large"
};

const FLOW_NODE_DEF_PATTERN =
  /^\s*([A-Za-z0-9_:.\/-]+)\s*(\[[^\]]*\]|\(\([^\)]*\)\)|\([^\)]*\)|\{[^\}]*\}|>\[[^\]]*\])/;

function normalizeMermaidSource(rawDiagram: string): string {
  const raw = rawDiagram || "flowchart LR\nA-->B";
  let normalized = raw.replace(/\r\n?/g, "\n");
  if (!normalized.includes("\n") && normalized.includes("\\n")) {
    normalized = normalized.replace(/\\n/g, "\n");
  }
  return normalized.replace(/\\"/g, '"').replace(/\\t/g, "\t");
}

function inferScale(diagramKind: DiagramKind | undefined, relationCount: number): DiagramScale {
  const hinted = diagramKind ? DIAGRAM_SCALE_HINT[diagramKind] : undefined;
  if (hinted) return hinted;
  if (relationCount > 140) return "large";
  if (relationCount > 44) return "medium";
  return "small";
}

function expandNeighborhood(
  seeds: Set<string>,
  adjacency: Map<string, Set<string>>,
  hops: number
): Set<string> {
  const keep = new Set<string>(seeds);
  let frontier = new Set<string>(seeds);
  for (let hop = 0; hop < hops; hop += 1) {
    const next = new Set<string>();
    for (const node of frontier) {
      for (const neighbor of adjacency.get(node) || []) {
        if (!keep.has(neighbor)) {
          keep.add(neighbor);
          next.add(neighbor);
        }
      }
    }
    frontier = next;
    if (frontier.size === 0) break;
  }
  return keep;
}

function parseFlowEdge(line: string): { from: string; to: string } | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  if (/^(classDef|class|style|linkStyle|subgraph|direction|click|%%|end\b)\b/i.test(trimmed)) return null;

  const fromMatch = trimmed.match(/^([A-Za-z0-9_:.\/-]+)/);
  const toMatch = trimmed.match(/([A-Za-z0-9_:.\/-]+)\s*;?\s*$/);
  if (!fromMatch || !toMatch) return null;

  const from = fromMatch[1];
  const to = toMatch[1];
  if (!from || !to || from === to) return null;

  const middle = trimmed.slice(fromMatch[0].length, trimmed.length - toMatch[0].length);
  if (!/(-->|==>|-.->|---|==|--|-\.|->)/.test(middle)) return null;
  return { from, to };
}

function parseClassAssignmentTargets(line: string): string[] | null {
  const trimmed = line.trim();
  if (!/^class\s+/i.test(trimmed) || /^classDef\s+/i.test(trimmed)) return null;
  const match = line.match(/^\s*class\s+(.+?)\s+[A-Za-z0-9_:-]+\s*;?\s*$/i);
  if (!match) return null;
  return match[1]
    .split(",")
    .map((token) => token.trim())
    .filter((token) => /^[A-Za-z0-9_:.\/-]+$/.test(token));
}

function scoreFlowEdge(line: string, diagramKind: DiagramKind | undefined): number {
  const value = line.toLowerCase();
  let score = 1;

  if (value.includes("high")) score += 2;
  else if (value.includes("medium")) score += 1;
  else if (value.includes("low")) score += 0.3;
  else score += 0.8;

  if (/(trust|boundary|auth|critical|secret|payment)/.test(value)) score += 1.8;
  if (/(depends_on|imports|uses|serves|exposes|api_call|request)/.test(value)) score += 1.2;
  if (/\bcalls\b/.test(value)) score += diagramKind === "call_graph" ? 0.7 : 0.4;
  if (/(error|retry|fallback)/.test(value)) score += 0.2;

  return score;
}

function preprocessErDiagram(
  source: string,
  detailLevel: DetailLevel,
  focusText: string,
  diagramKind: DiagramKind | undefined
): string {
  const lines = source.split("\n");
  const header = lines[0] || "erDiagram";
  const entityOrder: string[] = [];
  const entityBlocks = new Map<string, string[]>();
  const entityIndexRanges = new Map<string, [number, number]>();
  const entityIndex = new Map<string, number>();
  const entityAtIndex = new Map<number, string>();
  const passthroughIndices = new Set<number>();
  const relationRows: Array<{ index: number; from: string; to: string; line: string; score: number }> = [];

  let i = 1;
  while (i < lines.length) {
    const line = lines[i];
    const entityStart = line.match(/^\s*([A-Za-z0-9_]+)\s*\{\s*$/);
    if (entityStart) {
      const entity = entityStart[1];
      const start = i;
      const block: string[] = [line];
      i += 1;
      while (i < lines.length) {
        block.push(lines[i]);
        if (/^\s*\}\s*$/.test(lines[i])) break;
        i += 1;
      }
      const end = i;
      if (!entityIndex.has(entity)) {
        entityIndex.set(entity, entityOrder.length);
        entityOrder.push(entity);
      }
      entityBlocks.set(entity, block);
      entityIndexRanges.set(entity, [start, end]);
      for (let index = start; index <= end; index += 1) {
        entityAtIndex.set(index, entity);
      }
      i += 1;
      continue;
    }

    const relation = line.match(/^\s*([A-Za-z0-9_]+)\s+.*\s+([A-Za-z0-9_]+)\s*:/);
    if (relation) {
      relationRows.push({ index: i, from: relation[1], to: relation[2], line, score: 0 });
      i += 1;
      continue;
    }

    passthroughIndices.add(i);
    i += 1;
  }

  const adjacency = new Map<string, Set<string>>();
  const degree = new Map<string, number>();
  for (const row of relationRows) {
    if (!adjacency.has(row.from)) adjacency.set(row.from, new Set());
    if (!adjacency.has(row.to)) adjacency.set(row.to, new Set());
    adjacency.get(row.from)?.add(row.to);
    adjacency.get(row.to)?.add(row.from);
    degree.set(row.from, (degree.get(row.from) || 0) + 1);
    degree.set(row.to, (degree.get(row.to) || 0) + 1);
  }

  const normalizedFocus = focusText.trim().toLowerCase();
  const focusEntities = new Set<string>();
  if (normalizedFocus) {
    for (const entity of entityOrder) {
      if (entity.toLowerCase().includes(normalizedFocus)) {
        focusEntities.add(entity);
        continue;
      }
      const blockText = (entityBlocks.get(entity) || []).join(" ").toLowerCase();
      if (blockText.includes(normalizedFocus)) {
        focusEntities.add(entity);
      }
    }
  }

  const focusNeighborhood =
    focusEntities.size > 0 ? expandNeighborhood(focusEntities, adjacency, HOPS_FOR_LEVEL[detailLevel]) : null;

  const scale = inferScale(diagramKind, Math.max(relationRows.length, entityOrder.length));
  const entityCap = ER_ENTITY_CAP[detailLevel][scale];
  const relationCap = ER_RELATION_CAP[detailLevel][scale];

  const rankedEntities = [...entityOrder].sort((left, right) => {
    const degreeDiff = (degree.get(right) || 0) - (degree.get(left) || 0);
    if (degreeDiff !== 0) return degreeDiff;
    return (entityIndex.get(left) || 0) - (entityIndex.get(right) || 0);
  });
  const entityPool = focusNeighborhood
    ? rankedEntities.filter((entity) => focusNeighborhood.has(entity))
    : rankedEntities;

  const seedCount = detailLevel === "overview" ? 3 : 12;
  let keepEntities = new Set(entityPool.slice(0, Math.min(seedCount, entityCap)));
  if (keepEntities.size === 0) {
    keepEntities = new Set(entityPool.slice(0, Math.min(entityCap, entityPool.length)));
  }
  for (const entity of focusEntities) {
    if (keepEntities.size >= entityCap) break;
    keepEntities.add(entity);
  }

  const scoredRelations = relationRows
    .map((row) => {
      const endpointScore = (degree.get(row.from) || 0) + (degree.get(row.to) || 0);
      let score = endpointScore;
      if (focusNeighborhood) {
        const fromFocused = focusNeighborhood.has(row.from);
        const toFocused = focusNeighborhood.has(row.to);
        if (fromFocused && toFocused) score += 6;
        else if (fromFocused || toFocused) score += 2;
        else score -= 3;
      }
      return { ...row, score };
    })
    .sort((left, right) => right.score - left.score || left.index - right.index);

  const candidateRelations = focusNeighborhood
    ? scoredRelations.filter((row) => focusNeighborhood.has(row.from) && focusNeighborhood.has(row.to))
    : scoredRelations;

  const selectedRelations: Array<{ index: number; from: string; to: string; line: string; score: number }> = [];
  for (const relation of candidateRelations) {
    if (selectedRelations.length >= relationCap) break;
    const adds = Number(!keepEntities.has(relation.from)) + Number(!keepEntities.has(relation.to));
    if (keepEntities.size + adds > entityCap && adds > 0) continue;

    if (
      selectedRelations.length > 0 &&
      !keepEntities.has(relation.from) &&
      !keepEntities.has(relation.to) &&
      !focusNeighborhood
    ) {
      continue;
    }

    keepEntities.add(relation.from);
    keepEntities.add(relation.to);
    selectedRelations.push(relation);
  }

  if (keepEntities.size > entityCap) {
    const orderedKeep = entityPool.filter((entity) => keepEntities.has(entity)).slice(0, entityCap);
    keepEntities = new Set(orderedKeep);
  }

  if (keepEntities.size === 0 && entityOrder.length > 0) {
    keepEntities = new Set(entityOrder.slice(0, Math.min(entityCap, entityOrder.length)));
  }

  const keepRelationIndices = new Set<number>();
  for (const relation of selectedRelations) {
    if (keepEntities.has(relation.from) && keepEntities.has(relation.to)) {
      keepRelationIndices.add(relation.index);
    }
  }

  const output: string[] = [header];
  for (let index = 1; index < lines.length; index += 1) {
    const entity = entityAtIndex.get(index);
    if (entity && keepEntities.has(entity)) {
      output.push(lines[index]);
      continue;
    }
    if (keepRelationIndices.has(index)) {
      output.push(lines[index]);
      continue;
    }
    if (passthroughIndices.has(index)) {
      output.push(lines[index]);
    }
  }

  if (output.length === 1) {
    output.push("    NO_SCHEMA {");
    output.push("      string note");
    output.push("    }");
  }
  return output.join("\n");
}

function preprocessFlowDiagram(
  source: string,
  detailLevel: DetailLevel,
  focusText: string,
  diagramKind: DiagramKind | undefined
): string {
  const lines = source.split("\n");
  const header = lines[0] || "flowchart LR";
  const nodeOrder: string[] = [];
  const nodeIndex = new Map<string, number>();
  const nodeAtIndex = new Map<number, string>();
  const nodeIndicesById = new Map<string, number[]>();
  const classAssignments: Array<{ index: number; nodeIds: string[] }> = [];
  const passthroughIndices = new Set<number>();
  const edgeRows: Array<{ index: number; from: string; to: string; line: string; score: number }> = [];

  for (let index = 1; index < lines.length; index += 1) {
    const line = lines[index];
    const nodeMatch = line.match(FLOW_NODE_DEF_PATTERN);
    if (nodeMatch) {
      const nodeId = nodeMatch[1];
      if (!nodeIndex.has(nodeId)) {
        nodeIndex.set(nodeId, nodeOrder.length);
        nodeOrder.push(nodeId);
      }
      if (!nodeIndicesById.has(nodeId)) nodeIndicesById.set(nodeId, []);
      nodeIndicesById.get(nodeId)?.push(index);
      nodeAtIndex.set(index, nodeId);
      continue;
    }

    const edgeMatch = parseFlowEdge(line);
    if (edgeMatch) {
      edgeRows.push({ index, from: edgeMatch.from, to: edgeMatch.to, line, score: 0 });
      continue;
    }

    const classTargets = parseClassAssignmentTargets(line);
    if (classTargets) {
      classAssignments.push({ index, nodeIds: classTargets });
      continue;
    }

    passthroughIndices.add(index);
  }

  const degree = new Map<string, number>();
  const adjacency = new Map<string, Set<string>>();
  for (const edge of edgeRows) {
    degree.set(edge.from, (degree.get(edge.from) || 0) + 1);
    degree.set(edge.to, (degree.get(edge.to) || 0) + 1);
    if (!adjacency.has(edge.from)) adjacency.set(edge.from, new Set());
    if (!adjacency.has(edge.to)) adjacency.set(edge.to, new Set());
    adjacency.get(edge.from)?.add(edge.to);
    adjacency.get(edge.to)?.add(edge.from);
  }

  const normalizedFocus = focusText.trim().toLowerCase();
  const focusIds = new Set<string>();
  if (normalizedFocus) {
    for (const nodeId of nodeOrder) {
      if (nodeId.toLowerCase().includes(normalizedFocus)) {
        focusIds.add(nodeId);
        continue;
      }
      const definitionText = (nodeIndicesById.get(nodeId) || []).map((index) => lines[index]).join(" ").toLowerCase();
      if (definitionText.includes(normalizedFocus)) {
        focusIds.add(nodeId);
      }
    }
  }

  const focusNeighborhood = focusIds.size > 0 ? expandNeighborhood(focusIds, adjacency, HOPS_FOR_LEVEL[detailLevel]) : null;
  const scale = inferScale(diagramKind, edgeRows.length);
  const edgeCap = FLOW_EDGE_CAP[detailLevel][scale];
  const nodeCap = FLOW_NODE_CAP[detailLevel][scale];

  const scoredEdges = edgeRows
    .map((edge) => {
      const degreeScore = ((degree.get(edge.from) || 0) + (degree.get(edge.to) || 0)) * 0.2;
      let score = scoreFlowEdge(edge.line, diagramKind) + degreeScore;
      if (focusNeighborhood) {
        const fromFocused = focusNeighborhood.has(edge.from);
        const toFocused = focusNeighborhood.has(edge.to);
        if (fromFocused && toFocused) score += 5;
        else if (fromFocused || toFocused) score += 2;
        else score -= 3;
      }
      return { ...edge, score };
    })
    .sort((left, right) => right.score - left.score || left.index - right.index);

  const candidates = focusNeighborhood
    ? scoredEdges.filter((edge) => focusNeighborhood.has(edge.from) && focusNeighborhood.has(edge.to))
    : scoredEdges;

  const selectedEdges: Array<{ index: number; from: string; to: string; line: string; score: number }> = [];
  const keepNodeIds = new Set<string>();

  for (const nodeId of focusIds) {
    if (Number.isFinite(nodeCap) && keepNodeIds.size >= nodeCap) break;
    keepNodeIds.add(nodeId);
  }

  for (const edge of candidates) {
    if (selectedEdges.length >= edgeCap) break;
    const adds = Number(!keepNodeIds.has(edge.from)) + Number(!keepNodeIds.has(edge.to));
    if (Number.isFinite(nodeCap) && keepNodeIds.size + adds > nodeCap && adds > 0) continue;
    keepNodeIds.add(edge.from);
    keepNodeIds.add(edge.to);
    selectedEdges.push(edge);
  }

  if (selectedEdges.length === 0 && keepNodeIds.size === 0 && nodeOrder.length > 0) {
    const fallbackNodeCap = Number.isFinite(nodeCap) ? Math.max(1, nodeCap) : nodeOrder.length;
    for (const nodeId of nodeOrder.slice(0, fallbackNodeCap)) {
      keepNodeIds.add(nodeId);
    }
  }

  const keepEdgeIndices = new Set(selectedEdges.map((edge) => edge.index));
  const keepClassIndices = new Set<number>();
  for (const assignment of classAssignments) {
    if (assignment.nodeIds.some((nodeId) => keepNodeIds.has(nodeId))) {
      keepClassIndices.add(assignment.index);
    }
  }

  const output: string[] = [header];
  for (let index = 1; index < lines.length; index += 1) {
    const nodeId = nodeAtIndex.get(index);
    if (nodeId && keepNodeIds.has(nodeId)) {
      output.push(lines[index]);
      continue;
    }
    if (keepEdgeIndices.has(index)) {
      output.push(lines[index]);
      continue;
    }
    if (keepClassIndices.has(index)) {
      output.push(lines[index]);
      continue;
    }
    if (passthroughIndices.has(index)) {
      output.push(lines[index]);
    }
  }

  if (selectedEdges.length === 0) {
    output.push('    n_no_data["No connections visible for this level/filter"]');
  }

  return output.join("\n");
}

function preprocessDiagram(
  rawDiagram: string,
  detailLevel: DetailLevel,
  focusText: string,
  diagramKind?: DiagramKind
): string {
  const source = normalizeMermaidSource(rawDiagram);
  if (detailLevel === "full" && !focusText.trim()) {
    return source;
  }

  const lines = source.split("\n");
  const header = lines[0] || "flowchart LR";
  if (/^\s*erDiagram\b/i.test(header)) {
    return preprocessErDiagram(source, detailLevel, focusText, diagramKind);
  }
  if (!/^\s*(flowchart|graph)\b/i.test(header)) {
    return source;
  }
  return preprocessFlowDiagram(source, detailLevel, focusText, diagramKind);
}

export default function MermaidCard({
  diagram,
  title,
  compact = false,
  expanded = false,
  detailLevel = "full",
  focusText = "",
  diagramKind
}: Props) {
  const [inlineSvg, setInlineSvg] = useState<string>("");
  const [modalSvg, setModalSvg] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const processedDiagram = useMemo(
    () => preprocessDiagram(diagram, detailLevel, focusText, diagramKind),
    [diagram, detailLevel, focusText, diagramKind]
  );
  const diagramBaseId = useMemo(
    () => `m_${title.replace(/[^a-zA-Z0-9]/g, "_")}_${Math.random().toString(16).slice(2)}`,
    [title]
  );
  const inlineDiagramId = useMemo(() => `${diagramBaseId}_inline`, [diagramBaseId]);
  const modalDiagramId = useMemo(() => `${diagramBaseId}_modal`, [diagramBaseId]);
  const safeTitle = useMemo(() => title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, ""), [title]);
  const downloadableSvg = modalSvg || inlineSvg;
  const canDownload = downloadableSvg.includes("<svg");

  useEffect(() => {
    let active = true;

    async function render() {
      const graph = processedDiagram || "flowchart LR\nA-->B";
      const fallbackGraph = graph
        .split("\n")
        .filter((line) => !line.trim().startsWith("style "))
        .join("\n");

      try {
        mermaid.initialize({
          startOnLoad: false,
          theme: "default",
          securityLevel: "loose",
          fontFamily: "IBM Plex Sans"
        });
        const [inlineRendered, modalRendered] = await Promise.all([
          mermaid.render(inlineDiagramId, graph),
          mermaid.render(modalDiagramId, graph)
        ]);
        if (active) {
          setInlineSvg(inlineRendered.svg);
          setModalSvg(modalRendered.svg);
        }
      } catch {
        try {
          const [inlineRendered, modalRendered] = await Promise.all([
            mermaid.render(`${inlineDiagramId}_fallback`, fallbackGraph),
            mermaid.render(`${modalDiagramId}_fallback`, fallbackGraph)
          ]);
          if (active) {
            setInlineSvg(inlineRendered.svg);
            setModalSvg(modalRendered.svg);
          }
        } catch (fallbackError) {
          if (active) {
            const message = fallbackError instanceof Error ? fallbackError.message : String(fallbackError);
            const errorSvg = `<pre>Mermaid render error: ${message}</pre>`;
            setInlineSvg(errorSvg);
            setModalSvg(errorSvg);
          }
        }
      }
    }

    render();

    return () => {
      active = false;
    };
  }, [processedDiagram, inlineDiagramId, modalDiagramId]);

  useEffect(() => {
    setModalOpen(false);
  }, [processedDiagram, title]);

  useEffect(() => {
    if (!modalOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setModalOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [modalOpen]);

  async function copySource() {
    try {
      await navigator.clipboard.writeText(processedDiagram);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  function downloadSvg() {
    if (!canDownload) return;
    const blob = new Blob([downloadableSvg], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${safeTitle || "diagram"}.svg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function openModal() {
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
  }

  return (
    <div className="panel">
      <div className="diagram-header">
        <h2>{title}</h2>
      </div>
      <div
        className={`mermaid-shell mermaid-shell-interactive ${compact ? "compact" : ""} ${expanded ? "expanded" : ""}`}
        onClick={openModal}
        role="button"
        tabIndex={0}
        aria-label={`Open ${title} in modal`}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openModal();
          }
        }}
      >
        <div className="mermaid-static-content" dangerouslySetInnerHTML={{ __html: inlineSvg }} />
      </div>
      <p className="diagram-hint">Click to open full-screen modal.</p>
      <details className="diagram-raw">
        <summary>View Mermaid source</summary>
        <pre>{processedDiagram}</pre>
      </details>
      {modalOpen ? (
        <div className="diagram-modal-overlay" onClick={closeModal}>
          <div
            className="diagram-modal"
            role="dialog"
            aria-modal="true"
            aria-label={`${title} interactive modal`}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="diagram-header">
              <h2>{title}</h2>
              <div className="diagram-toolbar">
                <div className="diagram-actions">
                  <ActionButton
                    icon={copied ? "check" : "copy"}
                    label={copied ? "Copied" : "Copy"}
                    onClick={copySource}
                    success={copied}
                  />
                  <ActionButton icon="download" label="SVG" onClick={downloadSvg} disabled={!canDownload} />
                  <IconButton icon="close" label="Close modal" onClick={closeModal} />
                </div>
              </div>
            </div>
            <div className="mermaid-shell mermaid-shell-modal">
              <div
                className="mermaid-static-content mermaid-modal-static"
                dangerouslySetInnerHTML={{ __html: modalSvg || inlineSvg }}
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
