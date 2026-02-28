"use client";

import { useEffect, useMemo, useState } from "react";
import ForceGraphPanel from "../components/ForceGraphPanel";
import MermaidCard from "../components/MermaidCard";
import { fallbackData } from "../lib/fallback-data";
import { DashboardState, GraphEdge, GraphNode } from "../lib/types";

type DiagramTab = "architecture_services" | "architecture_code" | "architecture_iac" | "er" | "call_graph" | "dependencies";

type RepoListResponse = {
  repos: string[];
  defaultRepo: string | null;
};

const TABS: Array<{ id: DiagramTab; label: string }> = [
  { id: "architecture_services", label: "Architecture (Services)" },
  { id: "architecture_code", label: "Architecture (Code)" },
  { id: "architecture_iac", label: "Architecture (IaC)" },
  { id: "er", label: "ER" },
  { id: "call_graph", label: "Call Graph" },
  { id: "dependencies", label: "Dependencies" }
];

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
  return nodes.find((node) => node.id === nodeId);
}

function connectedEdges(edges: GraphEdge[], nodeId: string | null): GraphEdge[] {
  if (!nodeId) return [];
  return edges.filter((edge) => edge.from === nodeId || edge.to === nodeId).slice(0, 15);
}

export default function Page() {
  const [data, setData] = useState<DashboardState>(fallbackData);
  const [loaded, setLoaded] = useState(false);
  const [loadWarning, setLoadWarning] = useState<string>("");
  const [repos, setRepos] = useState<string[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>("");
  const [selectedTab, setSelectedTab] = useState<DiagramTab>("architecture_services");
  const [search, setSearch] = useState("");
  const [edgeType, setEdgeType] = useState("all");
  const [focusSelection, setFocusSelection] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  useEffect(() => {
    async function initialize() {
      const query = new URLSearchParams(window.location.search);
      const rawTab = query.get("tab");
      const tab = (rawTab === "architecture" ? "architecture_services" : rawTab) as DiagramTab | null;
      const repoFromQuery = query.get("repo") || "";
      if (tab && TABS.some((item) => item.id === tab)) {
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
    async function loadRepoDashboard(repo: string) {
      setLoaded(false);
      try {
        const response = await fetch(`/api/autopsy/${encodeURIComponent(repo)}`, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const payload = (await response.json()) as DashboardState;
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
    if (!selectedNodeId && focusSelection) {
      setFocusSelection(false);
    }
  }, [selectedNodeId, focusSelection]);

  const selectedNode = useMemo(
    () => findNode(data.graphs.nodes, selectedNodeId),
    [data.graphs.nodes, selectedNodeId]
  );
  const relatedEdges = useMemo(
    () => connectedEdges(data.graphs.edges, selectedNodeId),
    [data.graphs.edges, selectedNodeId]
  );

  const edgeTypeOptions = useMemo(() => {
    const options = new Set<string>();
    for (const edge of data.graphs.edges) {
      options.add(edge.type);
    }
    return ["all", ...Array.from(options).sort()];
  }, [data.graphs.edges]);
  const edgeTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const edge of data.graphs.edges) {
      counts[edge.type] = (counts[edge.type] || 0) + 1;
    }
    return counts;
  }, [data.graphs.edges]);
  const visibleEdgeCount = useMemo(
    () =>
      data.graphs.edges.filter(
        (edge) =>
          (edgeType === "all" || edge.type === edgeType) &&
          (!focusSelection || !selectedNodeId || edge.from === selectedNodeId || edge.to === selectedNodeId)
      ).length,
    [data.graphs.edges, edgeType, focusSelection, selectedNodeId]
  );
  const confidenceBreakdown = useMemo(
    () => Object.entries(data.analysis?.confidence_distribution || {}),
    [data.analysis?.confidence_distribution]
  );
  const routeRows = data.analysis?.routes || [];
  const entityRows = data.analysis?.entities || [];
  const iacSummary = data.analysis?.iac;

  return (
    <main>
      <section className="dashboard-header">
        <h1 className="dashboard-title">Code Autopsy X-Ray Dashboard</h1>
        <p className="dashboard-subtitle">
          Visualizing outputs from <code>code-autopsy/.autopsy-outputs/&lt;repo&gt;</code>.
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
        <div className="panel">
          <h2>Module Graph</h2>
          <div className="graph-controls">
            <input
              className="control-input"
              placeholder="Search module label"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <select className="control-select" value={edgeType} onChange={(event) => setEdgeType(event.target.value)}>
              {edgeTypeOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <button
              className={`toggle-btn ${focusSelection ? "active" : ""}`}
              type="button"
              onClick={() => setFocusSelection((value) => !value)}
              disabled={!selectedNodeId}
              title={selectedNodeId ? "Show only neighbors for selected node" : "Select a node first"}
            >
              Focus Selected
            </button>
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

        <div>
          <div className="panel">
            <h2>Diagram Tabs</h2>
            <div className="tab-list">
              {TABS.map((tab) => (
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

          <MermaidCard
            diagram={diagramForTab(data.diagrams, selectedTab)}
            title={TABS.find((tab) => tab.id === selectedTab)?.label || "Diagram"}
          />

          <div className="diagram-grid">
            {TABS.map((tab) => (
              <MermaidCard
                key={`all-${tab.id}`}
                title={`${tab.label} (Full View)`}
                diagram={diagramForTab(data.diagrams, tab.id)}
                compact
              />
            ))}
          </div>

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
