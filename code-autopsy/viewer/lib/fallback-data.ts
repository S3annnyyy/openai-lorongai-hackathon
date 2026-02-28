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
    architecture: `flowchart LR
users["Users / Clients"] --> frontend["Frontend Service"]
frontend --> api["API Service"]
api --> db["Datastore"]
`,
    architecture_services: `flowchart LR
users["Users / Clients"] --> frontend["Frontend Service"]
frontend --> api["API Service"]
api --> db["Datastore"]
`,
    architecture_code: `flowchart LR
entry["entry"] --> service["service"]
service --> db["db"]
`,
    architecture_iac: `flowchart LR
iac["IaC Source"] --> deploy["Provisioning / Deploy"]
deploy --> compute["Compute"]
`,
    er: `erDiagram
    NO_SCHEMA {
      string note
    }
`,
    call_graph: `flowchart LR
entry --> service
`,
    dependencies: `flowchart LR
entry --> service
`,
    sequence: `sequenceDiagram
    actor Client
    participant API
    participant Core
    Client->>API: GET /health
    API->>Core: handle request
    Core-->>API: payload
    API-->>Client: 200 OK
`,
    use_case: `flowchart LR
actor_client["User / Client"] --> uc_default(["Access application capability"])
`,
    json_data: `{
  "repo": {
    "name": "unavailable"
  },
  "analysis": {
    "routes": []
  }
}
`,
    yaml_data: `repo:
  name: "unavailable"
analysis:
  routes: []
`,
    terraform_drawio: ""
  },
  diagrams_plantuml: {
    json_data: `@startjson
{
  "repo": {
    "name": "unavailable"
  },
  "analysis": {
    "routes": []
  }
}
@endjson
`,
    yaml_data: `@startyaml
repo:
  name: "unavailable"
analysis:
  routes: []
@endyaml
`
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
