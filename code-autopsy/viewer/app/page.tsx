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

function sectionTextBlock(value: string, maxLines = 10): string {
  const lines = value.replace(/\r\n/g, "\n").split("\n").map((line) => line.trimEnd());
  if (lines.length <= maxLines) return lines.join("\n");
  return `${lines.slice(0, maxLines).join("\n")}\n...`;
}

function cleanMarkdownLine(line: string): string {
  return line
    .replace(/^#{1,6}\s+/, "")
    .replace(/^\s*[-*]\s+/, "")
    .replace(/^\s*\d+\.\s+/, "")
    .trim();
}

function renderAgentReport(report: string): JSX.Element {
  const cleaned = sectionTextBlock(report, 14)
    .replace(/```[a-zA-Z0-9_-]*/g, "")
    .replace(/```/g, "");
  const lines = cleaned
    .split("\n")
    .map((line) => cleanMarkdownLine(line))
    .filter((line) => line.length > 0);

  if (lines.length === 0) {
    return <p className="muted">No report generated for this iteration.</p>;
  }

  return (
    <ul className="agent-report-list">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
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
  const simulation = data.simulation;
  const simulationSummary = simulation?.summary;
  const checkpoints = simulation?.checkpoints || [];
  const riskPairs = simulationSummary?.risk_counts || [];
  const riskPriorityLines = riskPairs.slice(0, 3).map(([label, count]) => {
    return `${formatRiskLabel(label)}: ${count} signal${count === 1 ? "" : "s"} (${formatRiskPriority(count)})`;
  });
  const postPointers = simulationSummary?.post_work_pointers || [];
  const prePointers = simulationSummary?.pre_work_pointers || [];
  const featureSnapshot = simulationSummary?.feature_snapshot || [];

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
            <h3>Security Simulation</h3>
            {simulation ? (
              <div className="simulation-block">
                <h4>Run summary</h4>
                <ul className="side-list compact-list">
                  <li>
                    <strong>Status:</strong> {simulation.status}
                    {simulation.exit_code !== 0 ? ` (exit ${simulation.exit_code})` : null}
                  </li>
                  <li>
                    <strong>Run:</strong> {simulation.run_name}
                  </li>
                  <li>
                    <strong>Planned Features:</strong> {simulation.features_requested ?? "N/A"} /{" "}
                    {simulation.features_simulated}
                  </li>
                  <li>
                    <strong>Pace:</strong> {simulation.weeks_per_iteration} weeks/iteration
                    {simulation.simulation_weeks ? ` | Total: ${simulation.simulation_weeks} weeks` : ""}
                  </li>
                  <li>
                    <strong>Started:</strong> {safeDate(simulation.created_at_utc)}
                  </li>
                  <li>
                    <strong>Report:</strong> <code>{simulation.report_path}</code>
                  </li>
                  <li>
                    <strong>Manifest:</strong> <code>{simulation.manifest_path}</code>
                  </li>
                  {simulation.status_note ? (
                    <li>
                      <strong>Note:</strong> {simulation.status_note}
                    </li>
                  ) : null}
                </ul>
                {simulation.error ? <p className="note">Error: {simulation.error}</p> : null}

                <h4>What this means</h4>
                <ul className="side-list compact-list">
                  <li>The project was copied into a sandbox before making any changes.</li>
                  <li>Each successful iteration adds one feature and records agent findings.</li>
                  <li>Checkpoint metadata below is the same source used by `simulation_report.md`.</li>
                  <li>Use this report as your onboarding handoff for the next engineering cycle.</li>
                </ul>

                {simulationSummary ? (
                  <>
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
                        <p>
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
                    <h4>Quick pre-read list</h4>
                    <ul className="side-list compact-list">
                      {prePointers.map((pointer) => (
                        <li key={pointer}>{pointer}</li>
                      ))}
                    </ul>
                  </>
                ) : null}

                <h4>Iteration timeline (plain English)</h4>
                {checkpoints.length > 0 ? (
                  checkpoints.map((checkpoint, index) => (
                    <div key={checkpoint.tag}>
                      <p className="simulation-checkpoint-line">
                        <strong>
                          {statusBadge(checkpoint.status)} {checkpoint.tag}
                        </strong>{" "}
                        - {checkpoint.feature}
                      </p>
                      <p className="muted">
                        Result: {checkpoint.status} | Timestamp: {safeDate(checkpoint.timestamp_utc)} | Commit:{" "}
                        <code>{checkpoint.commit ? checkpoint.commit.slice(0, 8) : "N/A"}</code> | Changed files:{" "}
                        {checkpoint.changed_files}
                      </p>
                      {checkpoint.notes ? <p>Notes: {checkpoint.notes}</p> : null}
                      {index + 1 < checkpoints.length ? <hr className="report-separator" /> : null}
                    </div>
                  ))
                ) : (
                  <p className="muted">No per-iteration checkpoint rows available yet.</p>
                )}

                <h4>Detailed iteration log</h4>
                {checkpoints.length > 0 ? (
                  checkpoints.map((checkpoint, index) => (
                    <div key={`detail-${checkpoint.tag}`} className="simulation-checkpoint-detail">
                      <h5 className="simulation-checkpoint-title">
                        {checkpoint.tag} (Iteration {checkpoint.iteration.toString().padStart(3, "0")})
                      </h5>
                      <p>
                        <strong>Goal:</strong> {checkpoint.feature}
                      </p>
                      <p>
                        <strong>Status:</strong> {statusBadge(checkpoint.status)} {checkpoint.status}
                      </p>
                      <p>
                        <strong>Timestamp:</strong> {safeDate(checkpoint.timestamp_utc)}
                      </p>
                      <p>
                        <strong>Notes:</strong> {checkpoint.notes || "No notes recorded."}
                      </p>
                      <p>
                        <strong>Changed files:</strong> {checkpoint.changed_files}
                      </p>
                      <div className="simulation-agent-reports">
                        <div>
                          <strong>Red Team</strong>
                          <div className="agent-report-card">{renderAgentReport(checkpoint.red_team_report || "")}</div>
                        </div>
                        <div>
                          <strong>Blue Team</strong>
                          <div className="agent-report-card">{renderAgentReport(checkpoint.blue_team_report || "")}</div>
                        </div>
                        <div>
                          <strong>Refactorer</strong>
                          <div className="agent-report-card">{renderAgentReport(checkpoint.refactorer_report || "")}</div>
                        </div>
                        <div>
                          <strong>Historian</strong>
                          <div className="agent-report-card">{renderAgentReport(checkpoint.historian_report || "")}</div>
                        </div>
                      </div>
                      {index + 1 < checkpoints.length ? <hr className="report-separator" /> : null}
                    </div>
                  ))
                ) : (
                  <p className="muted">No detailed checkpoint notes were available.</p>
                )}

                {postPointers.length > 0 ? (
                  <>
                    <h4>What to do next</h4>
                    <ul className="side-list compact-list">
                      {postPointers.map((pointer) => (
                        <li key={pointer}>{pointer}</li>
                      ))}
                    </ul>
                  </>
                ) : null}

                {featureSnapshot.length > 0 ? (
                  <>
                    <h4>Feature snapshot</h4>
                    <ol className="side-list compact-list">
                      {featureSnapshot.map((entry) => (
                        <li key={entry}>{entry}</li>
                      ))}
                    </ol>
                  </>
                ) : null}
              </div>
            ) : (
              <p className="muted">No simulation run has been attached for this repo yet.</p>
            )}
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


