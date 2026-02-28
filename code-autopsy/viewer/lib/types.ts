export type GraphNode = {
  id: string;
  type: string;
  label: string;
  criticality: number;
  lang?: string;
};

export type GraphEdge = {
  from: string;
  to: string;
  type: string;
  weight?: number;
  confidence?: string;
  reason?: string;
};

export type DashboardState = {
  generated_at: string;
  summary: {
    repo_name: string;
    repo_root: string;
    languages: string[];
    frameworks: string[];
    entrypoints: string[];
    files_indexed: number;
    files_skipped: number;
    mode: string;
  };
  graphs: {
    nodes: GraphNode[];
    edges: GraphEdge[];
    cycles: string[][];
    hotspots: Array<{
      module: string;
      hotspot_score: number;
      coupling_in: number;
      coupling_out: number;
    }>;
    function_hotspots: Array<{
      function: string;
      fan_in: number;
      fan_out: number;
      hotspot_score: number;
    }>;
    core_leaf_tags: Record<string, string>;
  };
  diagrams: {
    architecture: string;
    er: string;
    call_graph: string;
    dependencies: string;
    terraform_drawio?: string;
  };
  onboarding: {
    start_here: string[];
    key_flows: Array<{ name: string; flow: string }>;
    glossary: Array<{ term: string; location: string; definition: string }>;
    change_safely: {
      tests_to_run: string[];
      critical_invariants: string[];
    };
  };
  kiv: {
    graph_3d: string;
  };
};
