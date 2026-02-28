import { DashboardState } from "./types";

export const fallbackData: DashboardState = {
  generated_at: new Date().toISOString(),
  summary: {
    repo_name: "unavailable",
    repo_root: "",
    languages: [],
    frameworks: [],
    entrypoints: [],
    files_indexed: 0,
    files_skipped: 0,
    mode: "xray"
  },
  graphs: {
    nodes: [
      { id: "file:entry", type: "module", label: "entry", criticality: 0.6 },
      { id: "file:service", type: "module", label: "service", criticality: 0.4 },
      { id: "external:db", type: "external", label: "db", criticality: 0.2 }
    ],
    edges: [
      { from: "file:entry", to: "file:service", type: "calls", confidence: "medium" },
      { from: "file:service", to: "external:db", type: "depends_on", confidence: "high" }
    ],
    cycles: [],
    hotspots: [{ module: "entry", hotspot_score: 0.6, coupling_in: 1, coupling_out: 1 }],
    function_hotspots: [],
    core_leaf_tags: { entry: "core", service: "leaf" }
  },
  diagrams: {
    architecture: "flowchart LR\\nentry[\\\"entry\\\"] --> service[\\\"service\\\"]\\nservice --> db[\\\"db\\\"]\\n",
    er: "erDiagram\\n    NO_SCHEMA {\\n      string note\\n    }\\n",
    call_graph: "flowchart LR\\nentry --> service\\n",
    dependencies: "flowchart LR\\nentry --> service\\n"
  },
  onboarding: {
    start_here: ["entry", "service"],
    key_flows: [{ name: "default", flow: "Request -> entry -> service -> datastore" }],
    glossary: [{ term: "Entity", location: "n/a", definition: "Fallback glossary item" }],
    change_safely: {
      tests_to_run: ["pytest", "npm test"],
      critical_invariants: ["Keep auth checks intact."]
    }
  },
  kiv: {
    graph_3d: "Deferred to Phase 2"
  }
};
