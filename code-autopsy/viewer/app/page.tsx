"use client";

import { useEffect, useMemo, useState } from "react";
import ForceGraphPanel from "../components/ForceGraphPanel";
import MermaidCard from "../components/MermaidCard";
import { fallbackData } from "../lib/fallback-data";
import { DashboardState, GraphEdge, GraphNode } from "../lib/types";

type DiagramTab = "architecture" | "er" | "call_graph" | "dependencies";

const TABS: Array<{ id: DiagramTab; label: string }> = [
  { id: "architecture", label: "Architecture" },
  { id: "er", label: "ER" },
  { id: "call_graph", label: "Call Graph" },
  { id: "dependencies", label: "Dependencies" }
];

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
  const [selectedTab, setSelectedTab] = useState<DiagramTab>("architecture");
  const [search, setSearch] = useState("");
  const [edgeType, setEdgeType] = useState("all");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const tab = query.get("tab") as DiagramTab | null;
    if (tab && TABS.some((item) => item.id === tab)) {
      setSelectedTab(tab);
    }
  }, []);

  useEffect(() => {
    async function load() {
      try {
        const response = await fetch("./data/latest/dashboard_state.json", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const payload = (await response.json()) as DashboardState;
        setData(payload);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setLoadWarning(`Using fallback data because dashboard_state.json was not loaded (${message}).`);
      } finally {
        setLoaded(true);
      }
    }
    load();
  }, []);

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

  return (
    <main>
      <section className="dashboard-header">
        <h1 className="dashboard-title">Code Autopsy X-Ray Dashboard</h1>
        <p className="dashboard-subtitle">
          2D interactive module graph + focused and full diagram views. 3D graph remains KIV (Phase 2).
        </p>
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
          </div>
          <div className="graph-shell">
            <ForceGraphPanel
              nodes={data.graphs.nodes}
              edges={data.graphs.edges}
              searchText={search}
              edgeType={edgeType}
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

          <MermaidCard diagram={data.diagrams[selectedTab]} title={TABS.find((tab) => tab.id === selectedTab)?.label || "Diagram"} />

          <div className="diagram-grid">
            {TABS.map((tab) => (
              <MermaidCard
                key={`all-${tab.id}`}
                title={`${tab.label} (Full View)`}
                diagram={data.diagrams[tab.id]}
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
        </div>
      </section>
    </main>
  );
}
