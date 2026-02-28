"use client";

import { useEffect, useMemo, useState } from "react";
import DrawioCard from "../components/DrawioCard";
import ForceGraphPanel from "../components/ForceGraphPanel";
import MermaidCard from "../components/MermaidCard";
import { fallbackData } from "../lib/fallback-data";
import { DashboardState, GraphEdge, GraphNode } from "../lib/types";

type DiagramTab = "architecture_services" | "architecture_code" | "architecture_iac" | "er" | "call_graph" | "dependencies";
type PrimaryTab = "module_graph" | DiagramTab;

type RepoListResponse = {
  repos: string[];
  defaultRepo: string | null;
};

const PRIMARY_TABS: Array<{ id: PrimaryTab; label: string }> = [
  { id: "architecture_services", label: "Architecture (Services)" },
  { id: "architecture_code", label: "Architecture (Code)" },
  { id: "architecture_iac", label: "Architecture (IaC)" },
  { id: "er", label: "ER" },
  { id: "call_graph", label: "Call Graph" },
  { id: "dependencies", label: "Dependencies" },
  { id: "module_graph", label: "Module Graph" }
];

function isDiagramTab(tab: PrimaryTab): tab is DiagramTab {
  return tab !== "module_graph";
}

function diagramForTab(diagrams: DashboardState["diagrams"], tab: DiagramTab): string {
  if (tab === "architecture_services") {
    return diagrams.architecture_services || diagrams.architecture;
  }
  if (tab === "architecture_code") {
    return diagrams.architecture_code || diagrams.architecture_services || diagrams.architecture;
  }
  if (tab === "architecture_iac") {
    return (
      diagrams.architecture_iac ||
      "flowchart LR\n    no_iac[\"No IaC artifacts detected\"]\n    hint[\"Add Terraform/CloudFormation/Kubernetes/Compose files\"]\n    no_iac --> hint\n"
    );
  }
  return diagrams[tab];
}

function findNode(nodes: GraphNode[], nodeId: string | null): GraphNode | undefined {
  if (!nodeId) return undefined;
  const found = nodes.find((node) => node.id === nodeId);
  if (found) return found;
  if (nodeId.startsWith("group:")) {
    return {
      id: nodeId,
      type: "module",
      label: nodeId.slice(6),
      criticality: 0,
    };
  }
  if (nodeId.startsWith("file:")) {
    return {
      id: nodeId,
      type: "module",
      label: nodeId.slice(5),
      criticality: 0,
    };
  }
  return undefined;
}

function connectedEdges(edges: GraphEdge[], nodeId: string | null): GraphEdge[] {
  if (!nodeId) return [];
  return edges.filter((edge) => edge.from === nodeId || edge.to === nodeId).slice(0, 15);
}

function statusBadge(status: string): "[OK]" | "[FAIL]" | "[WARN]" {
  if (status === "ok") {
    return "[OK]";
  }
  if (status === "failed") {
    return "[FAIL]";
  }
  return "[WARN]";
}

function formatRiskPriority(score: number): string {
  if (score >= 50) return "High";
  if (score >= 20) return "Medium";
  return "Watch";
}

function formatRiskLabel(label: string): string {
  return label
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("/");
}

function safeDate(value: string | undefined): string {
  if (!value) return "Unknown";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "Invalid date";
  return new Date(parsed).toLocaleString();
}

function cleanMarkdownLine(line: string): string {
  const withSeverityEmoji = line.replace(
    /\[(CRITICAL|HIGH|MEDIUM|SMALL|LOW)\]/gi,
    (_match, level: string) => {
      const normalized = level.toUpperCase();
      if (normalized === "CRITICAL") return "🚨";
      if (normalized === "HIGH") return "🔴";
      if (normalized === "MEDIUM") return "🟠";
      if (normalized === "SMALL") return "🟣";
      return "🔵";
    }
  );

  return withSeverityEmoji
    .replace(/^#{1,6}\s+/, "")
    .replace(/^\s*[-*]\s+/, "")
    .replace(/^\s*\d+\.\s+/, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*/g, "")
    .trim();
}

function isSeverityLabelRow(text: string): boolean {
  return /^(?:(?:🚨|🔴|🟠|🟣|🔵)\s+|(?:CRITICAL|HIGH|MEDIUM|SMALL|LOW)\b)/i.test(text);
}

function renderAgentReport(report: string): JSX.Element {
  const cleaned = report
    .replace(/\r\n/g, "\n")
    .replace(/```[a-zA-Z0-9_-]*/g, "")
    .replace(/```/g, "");
  const rawLines = cleaned.split("\n");
  const blocks: JSX.Element[] = [];
  let listBuffer: Array<{ text: string; noBullet: boolean }> = [];
  let paragraphBuffer: string[] = [];

  const flushList = () => {
    if (listBuffer.length === 0) return;
    const items = [...listBuffer];
    listBuffer = [];
    blocks.push(
      <ul className="agent-report-list" key={`list-${blocks.length}`}>
        {items.map((item, index) => (
          <li
            key={`${blocks.length}-${index}`}
            className={item.noBullet ? "agent-report-list-item no-bullet" : "agent-report-list-item"}
          >
            {item.text}
          </li>
        ))}
      </ul>
    );
  };

  const flushParagraph = () => {
    if (paragraphBuffer.length === 0) return;
    const text = paragraphBuffer.join(" ").trim();
    paragraphBuffer = [];
    if (!text) return;
    blocks.push(
      <p className="agent-report-paragraph" key={`p-${blocks.length}`}>
        {text}
      </p>
    );
  };

  for (const rawLine of rawLines) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      flushParagraph();
      continue;
    }

    if (/^#{1,6}\s+/.test(line)) {
      flushList();
      flushParagraph();
      blocks.push(
        <h6 className="agent-report-heading" key={`h-${blocks.length}`}>
          {cleanMarkdownLine(line)}
        </h6>
      );
      continue;
    }

    if (/^[-*]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      flushParagraph();
      const cleaned = cleanMarkdownLine(line);
      listBuffer.push({ text: cleaned, noBullet: isSeverityLabelRow(cleaned) });
      continue;
    }

    flushList();
    paragraphBuffer.push(cleanMarkdownLine(line));
  }

  flushList();
  flushParagraph();

  if (blocks.length === 0) {
    return <p className="muted">No report generated for this iteration.</p>;
  }

  return <div className="agent-report-content">{blocks}</div>;
}

function nodeModulePath(node: GraphNode): string | null {
  if (node.type !== "module") return null;
  if (node.id.startsWith("file:")) return node.id.slice(5);
  if (node.label.includes("/")) return node.label;
  return null;
}

function groupNodeIdForLevel(path: string, level: "service" | "package" | "file"): string {
  if (level === "file") return `file:${path}`;
  const depth = level === "service" ? 1 : 2;
  const parts = path.split("/").filter(Boolean);
  return `group:${parts.slice(0, Math.min(parts.length, depth)).join("/")}`;
}

function wrapPdfText(line: string, maxChars: number): string[] {
  if (!line) return [""];
  if (line.length <= maxChars) return [line];

  const result: string[] = [];
  const words = line.split(/\s+/);
  let current = "";
  for (const word of words) {
    if (!word) continue;
    if (!current) {
      if (word.length <= maxChars) {
        current = word;
      } else {
        for (let index = 0; index < word.length; index += maxChars) {
          result.push(word.slice(index, index + maxChars));
        }
      }
      continue;
    }

    const next = `${current} ${word}`;
    if (next.length <= maxChars) {
      current = next;
      continue;
    }

    result.push(current);
    if (word.length <= maxChars) {
      current = word;
    } else {
      current = "";
      for (let index = 0; index < word.length; index += maxChars) {
        result.push(word.slice(index, index + maxChars));
      }
    }
  }
  if (current) result.push(current);
  return result.length > 0 ? result : [""];
}

function escapePdfText(text: string): string {
  const ascii = text.replace(/[^\x20-\x7E]/g, " ");
  return ascii.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

type PdfLineStyle = "title" | "section" | "subsection" | "agent" | "meta" | "bullet" | "body" | "spacer";

function classifyPdfLine(rawLine: string): { style: PdfLineStyle; text: string } {
  const line = rawLine.trimEnd();
  const trimmed = line.trim();
  if (!trimmed) return { style: "spacer", text: "" };
  if (trimmed.startsWith("# ")) return { style: "title", text: trimmed.slice(2).trim() };
  if (trimmed.startsWith("## ")) return { style: "section", text: trimmed.slice(3).trim() };
  if (trimmed.startsWith("### ")) return { style: "subsection", text: trimmed.slice(4).trim() };
  if (trimmed.startsWith("#### ")) return { style: "agent", text: trimmed.slice(5).trim() };
  if (trimmed.startsWith("- ")) return { style: "bullet", text: trimmed.slice(2).trim() };
  if (
    /^(Generated|Run|Status|Pace|Planned Features|Report Path|Manifest Path|Note|Goal|Timestamp|Notes|Changed files)\s*:/.test(
      trimmed
    )
  ) {
    return { style: "meta", text: trimmed };
  }
  return { style: "body", text: trimmed };
}

function buildPdfDocumentFromText(rawText: string): Uint8Array {
  const pageWidth = 595;
  const pageHeight = 842;
  const margin = 40;
  const usableWidth = pageWidth - margin * 2;
  const styleMap: Record<
    PdfLineStyle,
    {
      fontSize: number;
      indent: number;
      before: number;
      after: number;
      color: [number, number, number];
      drawRuleAfter?: boolean;
      prefix?: string;
    }
  > = {
    title: { fontSize: 19, indent: 0, before: 0, after: 8, color: [0.07, 0.2, 0.45], drawRuleAfter: true },
    section: { fontSize: 14, indent: 0, before: 10, after: 4, color: [0.1, 0.24, 0.52], drawRuleAfter: true },
    subsection: { fontSize: 12, indent: 0, before: 8, after: 2, color: [0.1, 0.16, 0.28] },
    agent: { fontSize: 11, indent: 0, before: 8, after: 2, color: [0.12, 0.19, 0.34] },
    meta: { fontSize: 10, indent: 0, before: 2, after: 0, color: [0.09, 0.13, 0.21] },
    bullet: { fontSize: 10, indent: 10, before: 1, after: 0, color: [0.09, 0.13, 0.21], prefix: "- " },
    body: { fontSize: 10, indent: 0, before: 1, after: 0, color: [0.09, 0.13, 0.21] },
    spacer: { fontSize: 10, indent: 0, before: 6, after: 0, color: [0.09, 0.13, 0.21] },
  };

  const pageCommands: string[] = [""];
  let currentPage = 0;
  let cursorY = pageHeight - margin;

  const pushPage = () => {
    pageCommands.push("");
    currentPage += 1;
    cursorY = pageHeight - margin;
  };

  const ensureSpace = (height: number) => {
    if (cursorY - height < margin) {
      pushPage();
    }
  };

  const drawText = (
    text: string,
    fontSize: number,
    x: number,
    y: number,
    color: [number, number, number]
  ) => {
    const safe = escapePdfText(text);
    pageCommands[currentPage] +=
      `BT /F1 ${fontSize} Tf ${color[0]} ${color[1]} ${color[2]} rg ` +
      `1 0 0 1 ${x.toFixed(2)} ${y.toFixed(2)} Tm (${safe}) Tj ET\n`;
  };

  const drawRule = () => {
    ensureSpace(8);
    const y = cursorY - 2;
    pageCommands[currentPage] += `0.80 0.86 0.96 RG ${margin} ${y.toFixed(2)} m ${pageWidth - margin} ${y.toFixed(2)} l S\n`;
    cursorY -= 8;
  };

  const rawLines = rawText.replace(/\r\n/g, "\n").split("\n");
  if (rawLines.length === 0) {
    rawLines.push("Security Simulation Report");
  }

  for (const rawLine of rawLines) {
    const classified = classifyPdfLine(rawLine);
    const config = styleMap[classified.style];
    if (classified.style === "spacer") {
      cursorY -= config.before;
      continue;
    }

    cursorY -= config.before;
    const content = `${config.prefix || ""}${classified.text}`;
    const maxChars = Math.max(20, Math.floor((usableWidth - config.indent) / (config.fontSize * 0.52)));
    const wrapped = wrapPdfText(content, maxChars);
    const lineStep = config.fontSize * 1.38;
    for (const line of wrapped) {
      ensureSpace(lineStep);
      drawText(line, config.fontSize, margin + config.indent, cursorY, config.color);
      cursorY -= lineStep;
    }
    cursorY -= config.after;
    if (config.drawRuleAfter) {
      drawRule();
    }
  }

  const pageStreams = pageCommands.map((stream) =>
    stream.trim()
      ? stream
      : `BT /F1 12 Tf 0.1 0.2 0.45 rg 1 0 0 1 ${margin} ${pageHeight - margin} Tm (${escapePdfText(
          "Security Simulation Report"
        )}) Tj ET\n`
  );

  const objectCount = pageStreams.length * 2 + 3;
  const objects: string[] = new Array(objectCount + 1);
  objects[1] = "<< /Type /Catalog /Pages 2 0 R >>";

  const kids: string[] = [];
  for (let index = 0; index < pageStreams.length; index += 1) {
    const pageObject = 3 + index * 2;
    const contentObject = pageObject + 1;
    kids.push(`${pageObject} 0 R`);

    const stream = pageStreams[index];

    objects[contentObject] = `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`;
    objects[pageObject] =
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] ` +
      `/Resources << /Font << /F1 ${objectCount} 0 R >> >> /Contents ${contentObject} 0 R >>`;
  }

  objects[2] = `<< /Type /Pages /Kids [${kids.join(" ")}] /Count ${pageStreams.length} >>`;
  objects[objectCount] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>";

  let output = "%PDF-1.4\n";
  const offsets: number[] = new Array(objectCount + 1).fill(0);
  for (let objectId = 1; objectId <= objectCount; objectId += 1) {
    offsets[objectId] = output.length;
    output += `${objectId} 0 obj\n${objects[objectId]}\nendobj\n`;
  }

  const xrefOffset = output.length;
  output += `xref\n0 ${objectCount + 1}\n`;
  output += "0000000000 65535 f \n";
  for (let objectId = 1; objectId <= objectCount; objectId += 1) {
    output += `${offsets[objectId].toString().padStart(10, "0")} 00000 n \n`;
  }
  output += `trailer\n<< /Size ${objectCount + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return new TextEncoder().encode(output);
}

function buildSimulationReportMarkdownLike(
  simulation: NonNullable<DashboardState["simulation"]>,
  checkpoints: NonNullable<DashboardState["simulation"]>["checkpoints"] | undefined,
  postPointers: string[]
): string {
  const lines: string[] = [];
  const checkpointRows = checkpoints || [];

  lines.push("# Security Simulation Report");
  lines.push("");
  lines.push(`Generated: ${new Date().toISOString()}`);
  lines.push(`Run: ${simulation.run_name}`);
  lines.push(`Status: ${simulation.status}`);
  lines.push(`Pace: ${simulation.weeks_per_iteration} weeks/iteration`);
  lines.push(`Planned Features: ${simulation.features_requested ?? "N/A"} / ${simulation.features_simulated}`);
  lines.push(`Report Path: ${simulation.report_path}`);
  lines.push(`Manifest Path: ${simulation.manifest_path}`);
  if (simulation.status_note) lines.push(`Note: ${simulation.status_note}`);
  lines.push("");

  lines.push("## Detailed iteration log");
  if (checkpointRows.length === 0) {
    lines.push("No detailed checkpoint notes were available.");
  } else {
    for (const checkpoint of checkpointRows) {
      lines.push("");
      lines.push(`### ${checkpoint.tag} (Iteration ${checkpoint.iteration.toString().padStart(3, "0")})`);
      lines.push(`Goal: ${checkpoint.feature}`);
      lines.push(`Status: ${checkpoint.status}`);
      lines.push(`Timestamp: ${checkpoint.timestamp_utc}`);
      lines.push(`Notes: ${checkpoint.notes || "No notes recorded."}`);
      lines.push(`Changed files: ${checkpoint.changed_files}`);
      lines.push("");
      lines.push("#### Red Team");
      lines.push(checkpoint.red_team_report || "No red-team report was generated.");
      lines.push("");
      lines.push("#### Blue Team");
      lines.push(checkpoint.blue_team_report || "No blue-team report was generated.");
      lines.push("");
      lines.push("#### Refactorer");
      lines.push(checkpoint.refactorer_report || "No refactorer report was generated.");
      lines.push("");
      lines.push("#### Historian");
      lines.push(checkpoint.historian_report || "No historian report was generated.");
    }
  }

  if (postPointers.length > 0) {
    lines.push("");
    lines.push("## What to do next");
    for (const pointer of postPointers) {
      lines.push(`- ${pointer}`);
    }
  }

  lines.push("");
  return lines.join("\n");
}

export default function Page() {
  const [data, setData] = useState<DashboardState>(fallbackData);
  const [loaded, setLoaded] = useState(false);
  const [loadWarning, setLoadWarning] = useState<string>("");
  const [repos, setRepos] = useState<string[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>("");
  const [selectedTab, setSelectedTab] = useState<PrimaryTab>("architecture_services");
  const [search, setSearch] = useState("");
  const [edgeType, setEdgeType] = useState("depends_on");
  const [includeCalls, setIncludeCalls] = useState(false);
  const [maxEdges, setMaxEdges] = useState(300);
  const [graphLevel, setGraphLevel] = useState<"service" | "package" | "file">("service");
  const [drillPrefix, setDrillPrefix] = useState<string | null>(null);
  const [diagramDetail, setDiagramDetail] = useState<"overview" | "standard" | "full">("overview");
  const [diagramFocus, setDiagramFocus] = useState("");
  const [focusSelection, setFocusSelection] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedIterationTag, setSelectedIterationTag] = useState<string>("");
  const [expandedReport, setExpandedReport] = useState<{ title: string; content: string } | null>(null);

  useEffect(() => {
    async function initialize() {
      const query = new URLSearchParams(window.location.search);
      const rawTab = query.get("tab");
      const tab = (rawTab === "architecture" ? "architecture_services" : rawTab) as PrimaryTab | null;
      const repoFromQuery = query.get("repo") || "";
      if (tab && PRIMARY_TABS.some((item) => item.id === tab)) {
        setSelectedTab(tab);
      }

      try {
        const response = await fetch("/api/autopsy", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const payload = (await response.json()) as RepoListResponse;
        const repoList = payload.repos || [];
        setRepos(repoList);

        if (repoList.length === 0) {
          setLoadWarning(
            "No autopsy output found. Generate artifacts under code-autopsy/.autopsy-outputs/<repo_name>/."
          );
          setLoaded(true);
          return;
        }

        const repoToUse = repoList.includes(repoFromQuery)
          ? repoFromQuery
          : payload.defaultRepo || repoList[0];
        setSelectedRepo(repoToUse);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setLoadWarning(`Failed to list repos from .autopsy-outputs (${message}). Using fallback data.`);
        setLoaded(true);
      }
    }

    initialize();
  }, []);

  useEffect(() => {
    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        setTimeout(resolve, ms);
      });

    async function fetchDashboardWithRetry(repo: string): Promise<DashboardState> {
      const url = `/api/autopsy/${encodeURIComponent(repo)}`;
      let lastStatus = 0;
      let lastMessage = "Unknown error";

      for (let attempt = 1; attempt <= 3; attempt += 1) {
        try {
          const response = await fetch(url, { cache: "no-store" });
          if (response.ok) {
            return (await response.json()) as DashboardState;
          }
          lastStatus = response.status;
          lastMessage = `HTTP ${response.status}`;
        } catch (error) {
          lastMessage = error instanceof Error ? error.message : String(error);
        }

        if (attempt < 3) {
          await wait(180 * attempt);
        }
      }

      const hint =
        lastStatus >= 500
          ? " If this is Next.js dev cache drift, run: `rm -rf code-autopsy/viewer/.next` and restart `npm run dev`."
          : "";
      throw new Error(`${lastMessage}.${hint}`.trim());
    }

    async function loadRepoDashboard(repo: string) {
      setLoaded(false);
      try {
        const payload = await fetchDashboardWithRetry(repo);
        setData(payload);
        setLoadWarning("");
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setLoadWarning(`Using fallback data because dashboard_state.json was not loaded for '${repo}' (${message}).`);
      } finally {
        setLoaded(true);
      }
    }

    if (!selectedRepo) return;
    loadRepoDashboard(selectedRepo);
  }, [selectedRepo]);

  useEffect(() => {
    if (!selectedRepo) return;
    const url = new URL(window.location.href);
    url.searchParams.set("repo", selectedRepo);
    window.history.replaceState({}, "", url.toString());
  }, [selectedRepo]);

  useEffect(() => {
    setSelectedNodeId(null);
    setDrillPrefix(null);
    setGraphLevel("service");
    setDiagramFocus("");
    setDiagramDetail("overview");
  }, [selectedRepo]);

  useEffect(() => {
    if (!selectedNodeId && focusSelection) {
      setFocusSelection(false);
    }
  }, [selectedNodeId, focusSelection]);

  useEffect(() => {
    if (!expandedReport) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setExpandedReport(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [expandedReport]);

  const selectedNode = useMemo(
    () => findNode(data.graphs.nodes, selectedNodeId),
    [data.graphs.nodes, selectedNodeId]
  );
  const selectedNodeScope = useMemo(() => {
    if (!selectedNode) return null;
    if (selectedNode.id.startsWith("group:")) return selectedNode.id.slice(6);
    if (selectedNode.id.startsWith("file:")) return selectedNode.id.slice(5);
    if (selectedNode.type === "module" && selectedNode.label.includes("/")) return selectedNode.label;
    return null;
  }, [selectedNode]);
  const relatedEdges = useMemo(
    () => connectedEdges(data.graphs.edges, selectedNodeId),
    [data.graphs.edges, selectedNodeId]
  );

  const edgeTypeOptions = useMemo(() => {
    const options = new Set<string>();
    for (const edge of data.graphs.edges) {
      options.add(edge.type);
    }
    const sorted = Array.from(options).sort((left, right) => {
      const rank = (value: string): number => {
        if (value === "depends_on") return 0;
        if (value === "imports") return 1;
        if (value === "trust_boundary_crossing") return 2;
        if (value === "calls") return 3;
        return 4;
      };
      return rank(left) - rank(right) || left.localeCompare(right);
    });
    return ["all", ...sorted];
  }, [data.graphs.edges]);
  useEffect(() => {
    if (edgeTypeOptions.includes(edgeType)) return;
    if (edgeTypeOptions.includes("depends_on")) {
      setEdgeType("depends_on");
      return;
    }
    if (edgeTypeOptions.includes("imports")) {
      setEdgeType("imports");
      return;
    }
    setEdgeType("all");
  }, [edgeType, edgeTypeOptions]);
  const edgeTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const edge of data.graphs.edges) {
      counts[edge.type] = (counts[edge.type] || 0) + 1;
    }
    return counts;
  }, [data.graphs.edges]);
  const visibleEdgeCount = useMemo(() => {
    const nodeById = new Map(data.graphs.nodes.map((node) => [node.id, node]));
    const scopedNodeIds = new Set(
      data.graphs.nodes
        .filter((node) => {
          const path = nodeModulePath(node);
          if (!path) return true;
          if (!drillPrefix) return true;
          return path.startsWith(drillPrefix);
        })
        .map((node) => node.id)
    );

    const transformedEdges = data.graphs.edges
      .filter((edge) => {
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
      })
      .map((edge) => {
        const fromNode = nodeById.get(edge.from);
        const toNode = nodeById.get(edge.to);
        const fromPath = fromNode ? nodeModulePath(fromNode) : null;
        const toPath = toNode ? nodeModulePath(toNode) : null;
        const mappedFrom = fromPath ? groupNodeIdForLevel(fromPath, graphLevel) : edge.from;
        const mappedTo = toPath ? groupNodeIdForLevel(toPath, graphLevel) : edge.to;
        return { ...edge, from: mappedFrom, to: mappedTo };
      })
      .filter((edge) => edge.from !== edge.to);

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

    let filteredEdges = transformedEdges.filter((edge) => edgeType === "all" || edge.type === edgeType);
    if (!includeCalls && edgeType !== "calls") {
      filteredEdges = filteredEdges.filter((edge) => edge.type !== "calls");
    }
    if (focusSelection && selectedNodeId) {
      filteredEdges = filteredEdges.filter((edge) => edge.from === selectedNodeId || edge.to === selectedNodeId);
    }

    return [...filteredEdges]
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
      .slice(0, Math.max(40, maxEdges)).length;
  }, [
    data.graphs.edges,
    data.graphs.nodes,
    edgeType,
    includeCalls,
    maxEdges,
    focusSelection,
    selectedNodeId,
    graphLevel,
    drillPrefix,
  ]);
  const confidenceBreakdown = useMemo(
    () => Object.entries(data.analysis?.confidence_distribution || {}),
    [data.analysis?.confidence_distribution]
  );
  const routeRows = data.analysis?.routes || [];
  const entityRows = data.analysis?.entities || [];
  const iacSummary = data.analysis?.iac;
  const simulation = data.simulation;
  const simulationSummary = simulation?.summary;
  const checkpoints = simulation?.checkpoints || [];
  const riskPairs = simulationSummary?.risk_counts || [];
  const riskPriorityLines = riskPairs.slice(0, 3).map(([label, count]) => {
    return `${formatRiskLabel(label)}: ${count} signal${count === 1 ? "" : "s"} (${formatRiskPriority(count)})`;
  });
  const postPointers = simulationSummary?.post_work_pointers || [];
  const selectedDiagramTab = isDiagramTab(selectedTab) ? selectedTab : "architecture_services";
  const activeCheckpoint = checkpoints.find((item) => item.tag === selectedIterationTag) || checkpoints[0] || null;
  const openReportModal = (title: string, content: string) => {
    const text = content.trim() || "No report generated for this iteration.";
    setExpandedReport({ title, content: text });
  };
  const downloadSimulationPdf = () => {
    if (!simulation) return;
    const reportText = buildSimulationReportMarkdownLike(simulation, simulation.checkpoints, postPointers);
    const bytes = buildPdfDocumentFromText(reportText);
    const pdfBuffer = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(pdfBuffer).set(bytes);
    const blob = new Blob([pdfBuffer], { type: "application/pdf" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${simulation.run_name || "security-simulation-report"}.pdf`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  useEffect(() => {
    if (checkpoints.length === 0) {
      if (selectedIterationTag) {
        setSelectedIterationTag("");
      }
      return;
    }
    const hasSelected = checkpoints.some((item) => item.tag === selectedIterationTag);
    if (!hasSelected) {
      setSelectedIterationTag(checkpoints[0].tag);
    }
  }, [checkpoints, selectedIterationTag]);

  const drillIntoSelected = () => {
    if (!selectedNodeScope) return;
    if (graphLevel === "service") {
      setGraphLevel("package");
    } else if (graphLevel === "package") {
      setGraphLevel("file");
    }
    setDrillPrefix(selectedNodeScope);
    setSelectedNodeId(null);
  };

  const resetGraphScope = () => {
    setGraphLevel("service");
    setDrillPrefix(null);
    setSelectedNodeId(null);
  };

  return (
    <main>
      <section className="dashboard-header">
        <h1 className="dashboard-title">Code Autopsy X-Ray Dashboard</h1>
        <div className="dashboard-repo-selection">
          <p className="dashboard-subtitle">
          Visualizing outputs from <code>code-autopsy/.autopsy-outputs/</code>
          </p>
          <div className="graph-controls">
            <select
              className="control-select"
              value={selectedRepo}
              onChange={(event) => setSelectedRepo(event.target.value)}
              disabled={repos.length === 0}
            >
              {repos.length === 0 ? (
                <option value="">No repos found</option>
              ) : (
                repos.map((repo) => (
                  <option key={repo} value={repo}>
                    {repo}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>
        <div className="kpi-grid">
          <div className="kpi">
            <div className="kpi-label">Repository</div>
            <div className="kpi-value">{data.summary.repo_name}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Files Indexed</div>
            <div className="kpi-value">{data.summary.files_indexed}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Languages</div>
            <div className="kpi-value">{data.summary.languages.join(", ") || "None"}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Frameworks</div>
            <div className="kpi-value">{data.summary.frameworks.join(", ") || "None"}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Generated</div>
            <div className="kpi-value">{loaded ? new Date(data.generated_at).toLocaleString() : "Loading..."}</div>
          </div>
        </div>
        {loadWarning ? <p className="note">{loadWarning}</p> : null}
      </section>

      <section className="layout-grid">
        <div>
          <div className="panel">
            <h2>Visualization</h2>
            <div className="tab-list">
              {PRIMARY_TABS.map((tab) => (
                <button
                  key={tab.id}
                  className={`tab-btn ${selectedTab === tab.id ? "active" : ""}`}
                  onClick={() => {
                    setSelectedTab(tab.id);
                    const url = new URL(window.location.href);
                    url.searchParams.set("tab", tab.id);
                    window.history.replaceState({}, "", url.toString());
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {selectedTab === "module_graph" ? (
            <div className="panel">
              <h2>Module Graph</h2>
              <div className="graph-controls">
                <input
                  className="control-input"
                  placeholder="Search module label"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                <select
                  className="control-select"
                  value={graphLevel}
                  onChange={(event) => {
                    setGraphLevel(event.target.value as "service" | "package" | "file");
                    setSelectedNodeId(null);
                  }}
                >
                  <option value="service">Service Level</option>
                  <option value="package">Package Level</option>
                  <option value="file">File Level</option>
                </select>
                <select className="control-select" value={edgeType} onChange={(event) => setEdgeType(event.target.value)}>
                  {edgeTypeOptions.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
                <button
                  className={`toggle-btn ${includeCalls ? "active" : ""}`}
                  type="button"
                  onClick={() => setIncludeCalls((value) => !value)}
                  title="Calls are noisy; keep hidden by default unless needed"
                >
                  {includeCalls ? "Calls Visible" : "Show Calls"}
                </button>
                <button
                  className={`toggle-btn ${focusSelection ? "active" : ""}`}
                  type="button"
                  onClick={() => setFocusSelection((value) => !value)}
                  disabled={!selectedNodeId}
                  title={selectedNodeId ? "Show only neighbors for selected node" : "Select a node first"}
                >
                  Focus Selected
                </button>
                <button
                  className="toggle-btn"
                  type="button"
                  onClick={drillIntoSelected}
                  disabled={!selectedNodeScope || graphLevel === "file"}
                  title={!selectedNodeScope ? "Select a module/group node first" : "Drill into selected module scope"}
                >
                  Drill Into Selected
                </button>
                <button className="toggle-btn" type="button" onClick={resetGraphScope}>
                  Reset Scope
                </button>
              </div>
              <div className="scope-note">
                Scope: <strong>{drillPrefix || "all modules"}</strong> | Level: <strong>{graphLevel}</strong>
              </div>
              <div className="edge-budget">
                <label htmlFor="edgeBudget">Max visible edges: {maxEdges}</label>
                <input
                  id="edgeBudget"
                  type="range"
                  min={100}
                  max={1200}
                  step={50}
                  value={maxEdges}
                  onChange={(event) => setMaxEdges(Number(event.target.value))}
                />
              </div>
              <div className="graph-legend">
                <span className="legend-pill">
                  Visible Edges <strong>{visibleEdgeCount}</strong>
                </span>
                {Object.entries(edgeTypeCounts).map(([type, count]) => (
                  <span key={type} className={`legend-pill legend-${type}`}>
                    {type} <strong>{count}</strong>
                  </span>
                ))}
              </div>
              <div className="graph-shell">
                <ForceGraphPanel
                  nodes={data.graphs.nodes}
                  edges={data.graphs.edges}
                  searchText={search}
                  edgeType={edgeType}
                  includeCalls={includeCalls}
                  maxEdges={maxEdges}
                  graphLevel={graphLevel}
                  drillPrefix={drillPrefix}
                  focusSelection={focusSelection}
                  selectedNodeId={selectedNodeId}
                  onNodeSelect={setSelectedNodeId}
                />
              </div>
              <div className="node-meta">
                <strong>Selected Node:</strong> {selectedNode ? selectedNode.label : "None"}
                {selectedNode ? (
                  <>
                    <div>Type: {selectedNode.type}</div>
                    <div>Criticality: {selectedNode.criticality}</div>
                    <div>Connected Edges:</div>
                    <ul className="side-list">
                      {relatedEdges.map((edge, index) => (
                        <li key={`${edge.from}-${edge.to}-${index}`}>
                          {edge.type}: {edge.from} {"->"} {edge.to} ({edge.confidence || "n/a"})
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
                {confidenceBreakdown.length > 0 ? (
                  <>
                    <div className="meta-title">Edge Confidence</div>
                    <ul className="side-list compact-list">
                      {confidenceBreakdown.map(([bucket, count]) => (
                        <li key={bucket}>
                          <strong>{bucket}</strong>: {count}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </div>
            </div>
          ) : (
            <>
              <div className="panel">
                <h2>Diagram Controls</h2>
                <div className="graph-controls">
                  <select
                    className="control-select"
                    value={diagramDetail}
                    onChange={(event) => setDiagramDetail(event.target.value as "overview" | "standard" | "full")}
                  >
                    <option value="overview">Overview</option>
                    <option value="standard">Standard</option>
                    <option value="full">Full Detail</option>
                  </select>
                  <input
                    className="control-input"
                    placeholder="Focus diagram by node/module label"
                    value={diagramFocus}
                    onChange={(event) => setDiagramFocus(event.target.value)}
                  />
                </div>
              </div>
              <MermaidCard
                diagram={diagramForTab(data.diagrams, selectedDiagramTab)}
                title={PRIMARY_TABS.find((tab) => tab.id === selectedTab)?.label || "Diagram"}
                expanded
                detailLevel={diagramDetail}
                focusText={diagramFocus}
              />
            </>
          )}

          {data.diagrams.terraform_drawio ? (
            <DrawioCard title="Terraform IaC (draw.io)" xml={data.diagrams.terraform_drawio} />
          ) : null}

          <div className="panel">
            <div className="simulation-header-row">
              <h3 className="simulation-main-title">Security Simulation</h3>
              {simulation ? (
                <button type="button" className="simulation-download-btn" onClick={downloadSimulationPdf}>
                  Download PDF Report
                </button>
              ) : null}
            </div>
            {simulation ? (
              <div className="simulation-block">
                <div className="simulation-section">
                  <h4>Run summary</h4>
                  <ul className="simulation-summary-list">
                    <li>
                      <span className="summary-label">Status</span>
                      <span className="summary-value">
                        {simulation.status}
                        {simulation.exit_code !== 0 ? ` (exit ${simulation.exit_code})` : null}
                      </span>
                    </li>
                    <li>
                      <span className="summary-label">Run</span>
                      <span className="summary-value">{simulation.run_name}</span>
                    </li>
                    <li>
                      <span className="summary-label">Planned Features</span>
                      <span className="summary-value">
                        {simulation.features_requested ?? "N/A"} / {simulation.features_simulated}
                      </span>
                    </li>
                    <li>
                      <span className="summary-label">Pace</span>
                      <span className="summary-value">
                        {simulation.weeks_per_iteration} weeks/iteration
                        {simulation.simulation_weeks ? ` | Total: ${simulation.simulation_weeks} weeks` : ""}
                      </span>
                    </li>
                    <li>
                      <span className="summary-label">Started</span>
                      <span className="summary-value">{safeDate(simulation.created_at_utc)}</span>
                    </li>
                    <li>
                      <span className="summary-label">Report</span>
                      <code className="simulation-path">{simulation.report_path}</code>
                    </li>
                    <li>
                      <span className="summary-label">Manifest</span>
                      <code className="simulation-path">{simulation.manifest_path}</code>
                    </li>
                    {simulation.status_note ? (
                      <li>
                        <span className="summary-label">Note</span>
                        <span className="summary-value">{simulation.status_note}</span>
                      </li>
                    ) : null}
                  </ul>
                  {simulation.error ? <p className="note">Error: {simulation.error}</p> : null}
                </div>

                <div className="simulation-section">
                  <h4>What this means</h4>
                  <ul className="side-list compact-list">
                    <li>The project was copied into a sandbox before making any changes.</li>
                    <li>Each successful iteration adds one feature and records agent findings.</li>
                    <li>Checkpoint metadata below is the same source used by `simulation_report.md`.</li>
                    <li>Use this report as your onboarding handoff for the next engineering cycle.</li>
                  </ul>
                </div>

                {simulationSummary ? (
                  <div className="simulation-section">
                    <h4>Key repo insights for the next feature</h4>
                    <ul className="side-list compact-list">
                      <li>Planned features: {simulationSummary.requested_count}</li>
                      <li>Features completed in this run: {simulationSummary.features_completed}</li>
                      <li>Iteration success rate: {simulationSummary.iteration_success_rate.toFixed(0)}%</li>
                      <li>Last stable checkpoint: {simulationSummary.last_stable_checkpoint || "N/A"}</li>
                      <li>
                        Files touched most:
                        {simulationSummary.hotspot_lines.length > 0
                          ? ` ${simulationSummary.hotspot_lines.join(", ")}`
                          : " no repeat hotspots"}
                      </li>
                    </ul>

                    <h4>Priority now</h4>
                    {riskPriorityLines.length > 0 ? (
                      <>
                        <p className="simulation-highlight">
                          Main issues the simulation repeated:{" "}
                          {riskPriorityLines.join(", ")}
                        </p>
                        <ul className="side-list compact-list">
                          {riskPriorityLines.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </>
                    ) : (
                      <p>No repeated risk themes were detected.</p>
                    )}
                  </div>
                ) : null}

                <div className="simulation-section">
                  <h4>Detailed iteration log</h4>
                  {checkpoints.length > 0 ? (
                    <>
                    <div className="iteration-tabs">
                      {checkpoints.map((checkpoint) => (
                        <button
                          key={checkpoint.tag}
                          type="button"
                          className={`iteration-tab-btn ${selectedIterationTag === checkpoint.tag ? "active" : ""}`}
                          onClick={() => setSelectedIterationTag(checkpoint.tag)}
                          title={checkpoint.feature}
                        >
                          Iteration {checkpoint.iteration.toString().padStart(3, "0")}
                        </button>
                      ))}
                    </div>
                    {activeCheckpoint ? (
                      <div key={`detail-${activeCheckpoint.tag}`} className="simulation-checkpoint-detail">
                        <h5 className="simulation-checkpoint-title">
                          {activeCheckpoint.tag} (Iteration {activeCheckpoint.iteration.toString().padStart(3, "0")})
                        </h5>
                        <p>
                          <strong>Goal:</strong> {activeCheckpoint.feature}
                        </p>
                        <p>
                          <strong>Status:</strong> {statusBadge(activeCheckpoint.status)} {activeCheckpoint.status}
                        </p>
                        <p>
                          <strong>Timestamp:</strong> {safeDate(activeCheckpoint.timestamp_utc)}
                        </p>
                        <p>
                          <strong>Notes:</strong> {activeCheckpoint.notes || "No notes recorded."}
                        </p>
                        <p>
                          <strong>Changed files:</strong> {activeCheckpoint.changed_files}
                        </p>
                        <div className="simulation-agent-reports">
                          <div>
                            <strong>Red Team</strong>
                            <div
                              className="agent-report-card agent-report-card-interactive"
                              role="button"
                              tabIndex={0}
                              onClick={() =>
                                openReportModal(
                                  `Red Team - ${activeCheckpoint.tag}`,
                                  activeCheckpoint.red_team_report || ""
                                )
                              }
                              onKeyDown={(event) => {
                                if (event.key === "Enter" || event.key === " ") {
                                  event.preventDefault();
                                  openReportModal(
                                    `Red Team - ${activeCheckpoint.tag}`,
                                    activeCheckpoint.red_team_report || ""
                                  );
                                }
                              }}
                            >
                              <span className="agent-card-hover-hint">Open full report</span>
                              {renderAgentReport(activeCheckpoint.red_team_report || "")}
                            </div>
                          </div>
                          <div>
                            <strong>Blue Team</strong>
                            <div
                              className="agent-report-card agent-report-card-interactive"
                              role="button"
                              tabIndex={0}
                              onClick={() =>
                                openReportModal(
                                  `Blue Team - ${activeCheckpoint.tag}`,
                                  activeCheckpoint.blue_team_report || ""
                                )
                              }
                              onKeyDown={(event) => {
                                if (event.key === "Enter" || event.key === " ") {
                                  event.preventDefault();
                                  openReportModal(
                                    `Blue Team - ${activeCheckpoint.tag}`,
                                    activeCheckpoint.blue_team_report || ""
                                  );
                                }
                              }}
                            >
                              <span className="agent-card-hover-hint">Open full report</span>
                              {renderAgentReport(activeCheckpoint.blue_team_report || "")}
                            </div>
                          </div>
                          <div>
                            <strong>Refactorer</strong>
                            <div
                              className="agent-report-card agent-report-card-interactive"
                              role="button"
                              tabIndex={0}
                              onClick={() =>
                                openReportModal(
                                  `Refactorer - ${activeCheckpoint.tag}`,
                                  activeCheckpoint.refactorer_report || ""
                                )
                              }
                              onKeyDown={(event) => {
                                if (event.key === "Enter" || event.key === " ") {
                                  event.preventDefault();
                                  openReportModal(
                                    `Refactorer - ${activeCheckpoint.tag}`,
                                    activeCheckpoint.refactorer_report || ""
                                  );
                                }
                              }}
                            >
                              <span className="agent-card-hover-hint">Open full report</span>
                              {renderAgentReport(activeCheckpoint.refactorer_report || "")}
                            </div>
                          </div>
                          <div>
                            <strong>Historian</strong>
                            <div
                              className="agent-report-card agent-report-card-interactive"
                              role="button"
                              tabIndex={0}
                              onClick={() =>
                                openReportModal(
                                  `Historian - ${activeCheckpoint.tag}`,
                                  activeCheckpoint.historian_report || ""
                                )
                              }
                              onKeyDown={(event) => {
                                if (event.key === "Enter" || event.key === " ") {
                                  event.preventDefault();
                                  openReportModal(
                                    `Historian - ${activeCheckpoint.tag}`,
                                    activeCheckpoint.historian_report || ""
                                  );
                                }
                              }}
                            >
                              <span className="agent-card-hover-hint">Open full report</span>
                              {renderAgentReport(activeCheckpoint.historian_report || "")}
                            </div>
                          </div>
                        </div>
                      </div>
                    ) : null}
                    </>
                  ) : (
                    <p className="muted">No detailed checkpoint notes were available.</p>
                  )}
                </div>

                {postPointers.length > 0 ? (
                  <div className="simulation-section">
                    <h4>What to do next</h4>
                    <ul className="side-list compact-list">
                      {postPointers.map((pointer) => (
                        <li key={pointer}>{pointer}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

              </div>
            ) : (
              <p className="muted">No simulation run has been attached for this repo yet.</p>
            )}
            {expandedReport ? (
              <div className="report-modal-overlay" onClick={() => setExpandedReport(null)}>
                <div
                  className="report-modal"
                  role="dialog"
                  aria-modal="true"
                  aria-label={expandedReport.title}
                  onClick={(event) => event.stopPropagation()}
                >
                  <div className="report-modal-header">
                    <h4>{expandedReport.title}</h4>
                    <button
                      type="button"
                      className="report-modal-close"
                      onClick={() => setExpandedReport(null)}
                    >
                      Close
                    </button>
                  </div>
                  <div className="report-modal-body">{renderAgentReport(expandedReport.content)}</div>
                </div>
              </div>
            ) : null}
          </div>

          <div className="panel">
            <h3>Detected Routes</h3>
            {routeRows.length === 0 ? (
              <p className="muted">No routes detected.</p>
            ) : (
              <div className="table-shell">
                <table>
                  <thead>
                    <tr>
                      <th>Method</th>
                      <th>Path</th>
                      <th>File</th>
                    </tr>
                  </thead>
                  <tbody>
                    {routeRows.slice(0, 16).map((route, index) => (
                      <tr key={`${route.file}-${route.path}-${index}`}>
                        <td>{route.method}</td>
                        <td>{route.path}</td>
                        <td>{route.file}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <h3>Detected Entities</h3>
            {entityRows.length === 0 ? (
              <p className="muted">No entities detected (ER fallback expected).</p>
            ) : (
              <ul className="side-list compact-list">
                {entityRows.slice(0, 12).map((entity) => (
                  <li key={`${entity.name}-${entity.source || "unknown"}`}>
                    <strong>{entity.name}</strong> ({entity.format || "unknown"}) in{" "}
                    <code>{entity.source || "unknown"}</code>
                  </li>
                ))}
              </ul>
            )}
            <h3>IaC Footprint</h3>
            <ul className="side-list compact-list">
              <li>
                <strong>IaC Files</strong>: {iacSummary?.files ?? 0}
              </li>
              <li>
                <strong>IaC Resources</strong>: {iacSummary?.resources ?? 0}
              </li>
              <li>
                <strong>Providers</strong>:{" "}
                {Object.keys(iacSummary?.providers || {}).length
                  ? Object.keys(iacSummary?.providers || {})
                      .sort()
                      .join(", ")
                  : "None detected"}
              </li>
            </ul>
          </div>

          {data.narrative?.repo_summary_markdown ? (
            <div className="panel">
              <h3>Repo Summary</h3>
              <pre className="summary-block">{data.narrative.repo_summary_markdown}</pre>
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
