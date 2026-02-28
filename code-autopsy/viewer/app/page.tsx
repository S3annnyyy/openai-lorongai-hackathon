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
  const selectedDiagramTab = isDiagramTab(selectedTab) ? selectedTab : "architecture_services";

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
            <h3>Start Here</h3>
            <ol className="side-list">
              {data.onboarding.start_here.map((item) => (
                <li key={item} className="side-item">
                  <code>{item}</code>
                </li>
              ))}
            </ol>
            <h3>Key Flows</h3>
            <ul className="side-list">
              {data.onboarding.key_flows.map((flow) => (
                <li key={flow.name} className="side-item">
                  <strong>{flow.name}</strong>: {flow.flow}
                </li>
              ))}
            </ul>
            <h3>KIV</h3>
            <p>{data.kiv.graph_3d}</p>
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
