"use client";

import { useMemo } from "react";

type Props = {
  xml?: string;
  title: string;
  compact?: boolean;
};

type DrawioNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  fill: string;
  stroke: string;
};

type DrawioEdge = {
  id: string;
  from: string;
  to: string;
  label: string;
};

type ParsedDiagram = {
  nodes: DrawioNode[];
  edges: DrawioEdge[];
  width: number;
  height: number;
  error: string;
};

function parseStyle(styleText: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const part of styleText.split(";")) {
    const [key, value] = part.split("=");
    if (!key || value === undefined) continue;
    result[key.trim()] = value.trim();
  }
  return result;
}

function normalizeLabel(value: string): string {
  return value.replace(/&#xa;/g, "\n").replace(/\r/g, "").trim();
}

function parseDrawio(xml: string): ParsedDiagram {
  const fallback: ParsedDiagram = { nodes: [], edges: [], width: 1200, height: 520, error: "" };
  if (!xml || xml.trim().length === 0) {
    return fallback;
  }

  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xml, "application/xml");
    if (doc.querySelector("parsererror")) {
      return { ...fallback, error: "Invalid draw.io XML." };
    }

    const cells = Array.from(doc.getElementsByTagName("mxCell"));
    const nodes: DrawioNode[] = [];
    const edges: DrawioEdge[] = [];

    for (const cell of cells) {
      if (cell.getAttribute("vertex") !== "1") continue;
      const id = cell.getAttribute("id") || "";
      const style = parseStyle(cell.getAttribute("style") || "");
      const geometry = cell.getElementsByTagName("mxGeometry")[0];
      if (!geometry) continue;

      const x = Number(geometry.getAttribute("x") || "0");
      const y = Number(geometry.getAttribute("y") || "0");
      const width = Number(geometry.getAttribute("width") || "220");
      const height = Number(geometry.getAttribute("height") || "70");
      const label = normalizeLabel(cell.getAttribute("value") || "");

      nodes.push({
        id,
        label,
        x,
        y,
        width,
        height,
        fill: style.fillColor || "#e2e8f0",
        stroke: style.strokeColor || "#475569"
      });
    }

    for (const cell of cells) {
      if (cell.getAttribute("edge") !== "1") continue;
      const source = cell.getAttribute("source") || "";
      const target = cell.getAttribute("target") || "";
      if (!source || !target) continue;
      edges.push({
        id: cell.getAttribute("id") || `${source}_${target}`,
        from: source,
        to: target,
        label: normalizeLabel(cell.getAttribute("value") || "")
      });
    }

    const maxX = Math.max(1200, ...nodes.map((node) => node.x + node.width + 80));
    const maxY = Math.max(520, ...nodes.map((node) => node.y + node.height + 80));
    return { nodes, edges, width: maxX, height: maxY, error: "" };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ...fallback, error: message };
  }
}

export default function DrawioCard({ xml = "", title, compact = false }: Props) {
  const parsed = useMemo(() => parseDrawio(xml), [xml]);

  if (!xml) {
    return (
      <div className="panel">
        <h2>{title}</h2>
        <p className="note">No draw.io diagram found for this repo.</p>
      </div>
    );
  }

  if (parsed.error) {
    return (
      <div className="panel">
        <h2>{title}</h2>
        <pre className="drawio-error">draw.io render error: {parsed.error}</pre>
      </div>
    );
  }

  const nodeMap = new Map(parsed.nodes.map((node) => [node.id, node]));

  return (
    <div className="panel">
      <h2>{title}</h2>
      <div className={`drawio-shell ${compact ? "compact" : ""}`}>
        <svg
          className="drawio-svg"
          viewBox={`0 0 ${parsed.width} ${parsed.height}`}
          role="img"
          aria-label={title}
          preserveAspectRatio="xMidYMin meet"
        >
          <defs>
            <marker id="drawio-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
            </marker>
          </defs>

          {parsed.edges.map((edge) => {
            const source = nodeMap.get(edge.from);
            const target = nodeMap.get(edge.to);
            if (!source || !target) return null;
            const x1 = source.x + source.width / 2;
            const y1 = source.y + source.height / 2;
            const x2 = target.x + target.width / 2;
            const y2 = target.y + target.height / 2;
            const labelX = (x1 + x2) / 2;
            const labelY = (y1 + y2) / 2 - 6;
            return (
              <g key={edge.id}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#64748b" strokeWidth="2" markerEnd="url(#drawio-arrow)" />
                {edge.label ? (
                  <text x={labelX} y={labelY} textAnchor="middle" className="drawio-edge-label">
                    {edge.label}
                  </text>
                ) : null}
              </g>
            );
          })}

          {parsed.nodes.map((node) => {
            const lines = node.label.split("\n").filter((line) => line.trim().length > 0).slice(0, 5);
            return (
              <g key={node.id}>
                <rect
                  x={node.x}
                  y={node.y}
                  width={node.width}
                  height={node.height}
                  rx={10}
                  ry={10}
                  fill={node.fill}
                  stroke={node.stroke}
                  strokeWidth="2"
                />
                <text x={node.x + 10} y={node.y + 22} className="drawio-node-label">
                  {lines.map((line, index) => (
                    <tspan key={`${node.id}-${index}`} x={node.x + 10} dy={index === 0 ? 0 : 16}>
                      {line}
                    </tspan>
                  ))}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
