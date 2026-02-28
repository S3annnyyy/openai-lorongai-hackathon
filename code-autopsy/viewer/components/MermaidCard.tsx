"use client";

import mermaid from "mermaid";
import { useEffect, useMemo, useState } from "react";

type Props = {
  diagram: string;
  title: string;
  compact?: boolean;
  expanded?: boolean;
  detailLevel?: "overview" | "standard" | "full";
  focusText?: string;
};

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

const EDGE_LIMIT: Record<"overview" | "standard" | "full", number> = {
  overview: 36,
  standard: 120,
  full: 5000
};

const HOPS_FOR_LEVEL: Record<"overview" | "standard" | "full", number> = {
  overview: 1,
  standard: 2,
  full: 4
};

function normalizeMermaidSource(rawDiagram: string): string {
  const raw = rawDiagram || "flowchart LR\nA-->B";
  let normalized = raw.replace(/\r\n?/g, "\n");
  if (!normalized.includes("\n") && normalized.includes("\\n")) {
    normalized = normalized.replace(/\\n/g, "\n");
  }
  return normalized.replace(/\\"/g, '"').replace(/\\t/g, "\t");
}

function preprocessDiagram(
  rawDiagram: string,
  detailLevel: "overview" | "standard" | "full",
  focusText: string
): string {
  const source = normalizeMermaidSource(rawDiagram);
  if (detailLevel === "full" && !focusText.trim()) {
    return source;
  }

  const lines = source.split("\n");
  const header = lines[0] || "flowchart LR";
  if (/^\s*erDiagram\b/i.test(header)) {
    const entityBlocks = new Map<string, string[]>();
    const entityOrder: string[] = [];
    const relationRows: Array<{ from: string; to: string; line: string }> = [];

    let i = 1;
    while (i < lines.length) {
      const line = lines[i];
      const start = line.match(/^\s*([A-Za-z0-9_]+)\s*\{\s*$/);
      if (start) {
        const entity = start[1];
        const block: string[] = [line];
        i += 1;
        while (i < lines.length) {
          block.push(lines[i]);
          if (/^\s*\}\s*$/.test(lines[i])) break;
          i += 1;
        }
        entityBlocks.set(entity, block);
        entityOrder.push(entity);
        i += 1;
        continue;
      }

      const relation = line.match(/^\s*([A-Za-z0-9_]+)\s+.*\s+([A-Za-z0-9_]+)\s*:/);
      if (relation) {
        relationRows.push({ from: relation[1], to: relation[2], line });
      }
      i += 1;
    }

    let filteredRelations = [...relationRows];
    const normalizedFocus = focusText.trim().toLowerCase();
    if (normalizedFocus) {
      const focusEntities = new Set(entityOrder.filter((entity) => entity.toLowerCase().includes(normalizedFocus)));
      if (focusEntities.size > 0) {
        const adjacency = new Map<string, Set<string>>();
        for (const row of relationRows) {
          if (!adjacency.has(row.from)) adjacency.set(row.from, new Set());
          if (!adjacency.has(row.to)) adjacency.set(row.to, new Set());
          adjacency.get(row.from)?.add(row.to);
          adjacency.get(row.to)?.add(row.from);
        }
        const keep = new Set<string>(focusEntities);
        let frontier = new Set<string>(focusEntities);
        const hops = HOPS_FOR_LEVEL[detailLevel];
        for (let hop = 0; hop < hops; hop += 1) {
          const next = new Set<string>();
          for (const entity of frontier) {
            for (const neighbor of adjacency.get(entity) || []) {
              if (!keep.has(neighbor)) {
                keep.add(neighbor);
                next.add(neighbor);
              }
            }
          }
          frontier = next;
          if (frontier.size === 0) break;
        }
        filteredRelations = relationRows.filter((row) => keep.has(row.from) && keep.has(row.to));
      }
    }

    filteredRelations = filteredRelations.slice(0, EDGE_LIMIT[detailLevel]);
    const keepEntities = new Set<string>();
    for (const row of filteredRelations) {
      keepEntities.add(row.from);
      keepEntities.add(row.to);
    }
    if (keepEntities.size === 0 && entityOrder.length > 0) {
      const limit = detailLevel === "overview" ? 6 : detailLevel === "standard" ? 12 : entityOrder.length;
      for (const entity of entityOrder.slice(0, limit)) keepEntities.add(entity);
    }

    const output: string[] = [header];
    for (const entity of entityOrder) {
      if (!keepEntities.has(entity)) continue;
      for (const blockLine of entityBlocks.get(entity) || []) {
        output.push(blockLine);
      }
    }
    for (const row of filteredRelations) {
      output.push(row.line);
    }
    if (output.length === 1) {
      output.push("    NO_SCHEMA {");
      output.push("      string note");
      output.push("    }");
    }
    return output.join("\n");
  }

  if (!/^\s*(flowchart|graph)\b/i.test(header)) {
    return source;
  }

  const parseFlowEdge = (line: string): { from: string; to: string } | null => {
    const trimmed = line.trim();
    if (!trimmed) return null;
    if (/^(classDef|class|style|linkStyle|subgraph|direction|click)\b/i.test(trimmed)) return null;

    const fromMatch = trimmed.match(/^([A-Za-z0-9_]+)/);
    const toMatch = trimmed.match(/([A-Za-z0-9_]+)\s*;?\s*$/);
    if (!fromMatch || !toMatch) return null;

    const from = fromMatch[1];
    const to = toMatch[1];
    if (!from || !to || from === to) return null;

    const middle = trimmed.slice(fromMatch[0].length, trimmed.length - toMatch[0].length);
    if (!/[-=]/.test(middle)) return null;
    return { from, to };
  };

  const nodeDefs = new Map<string, string>();
  const nodeOrder: string[] = [];
  const edgeRows: Array<{ from: string; to: string; line: string }> = [];

  for (const line of lines.slice(1)) {
    const nodeMatch = line.match(/^\s*([A-Za-z0-9_]+)\s*(\[[^\]]*\]|\(\([^\)]*\)\)|\([^\)]*\)|\{[^\}]*\})/);
    if (nodeMatch) {
      const id = nodeMatch[1];
      if (!nodeDefs.has(id)) nodeOrder.push(id);
      nodeDefs.set(id, line);
      continue;
    }
    const edgeMatch = parseFlowEdge(line);
    if (edgeMatch) {
      edgeRows.push({ from: edgeMatch.from, to: edgeMatch.to, line });
    }
  }

  let filteredEdges = [...edgeRows];
  const normalizedFocus = focusText.trim().toLowerCase();
  if (normalizedFocus) {
    const focusIds = new Set<string>();
    for (const id of nodeOrder) {
      const def = nodeDefs.get(id) || "";
      if (id.toLowerCase().includes(normalizedFocus) || def.toLowerCase().includes(normalizedFocus)) {
        focusIds.add(id);
      }
    }

    if (focusIds.size > 0) {
      const adjacency = new Map<string, Set<string>>();
      for (const edge of edgeRows) {
        if (!adjacency.has(edge.from)) adjacency.set(edge.from, new Set<string>());
        if (!adjacency.has(edge.to)) adjacency.set(edge.to, new Set<string>());
        adjacency.get(edge.from)?.add(edge.to);
        adjacency.get(edge.to)?.add(edge.from);
      }

      const keep = new Set<string>(focusIds);
      let frontier = new Set<string>(focusIds);
      const hops = HOPS_FOR_LEVEL[detailLevel];
      for (let i = 0; i < hops; i += 1) {
        const next = new Set<string>();
        for (const id of frontier) {
          for (const neighbor of adjacency.get(id) || []) {
            if (!keep.has(neighbor)) {
              keep.add(neighbor);
              next.add(neighbor);
            }
          }
        }
        frontier = next;
        if (frontier.size === 0) break;
      }

      filteredEdges = edgeRows.filter((edge) => keep.has(edge.from) && keep.has(edge.to));
    }
  }

  filteredEdges = filteredEdges.slice(0, EDGE_LIMIT[detailLevel]);
  const keepNodeIds = new Set<string>();
  for (const edge of filteredEdges) {
    keepNodeIds.add(edge.from);
    keepNodeIds.add(edge.to);
  }

  const output = [header];
  for (const id of nodeOrder) {
    if (!keepNodeIds.has(id)) continue;
    const line = nodeDefs.get(id);
    if (line) output.push(line);
  }

  for (const edge of filteredEdges) {
    output.push(edge.line);
  }

  if (filteredEdges.length === 0) {
    output.push('    n_no_data["No connections visible for this level/filter"]');
  }

  return output.join("\n");
}

export default function MermaidCard({
  diagram,
  title,
  compact = false,
  expanded = false,
  detailLevel = "full",
  focusText = ""
}: Props) {
  const [inlineSvg, setInlineSvg] = useState<string>("");
  const [modalSvg, setModalSvg] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const processedDiagram = useMemo(
    () => preprocessDiagram(diagram, detailLevel, focusText),
    [diagram, detailLevel, focusText]
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
