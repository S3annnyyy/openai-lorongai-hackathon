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
  analysis?: {
    routes?: Array<{
      method: string;
      path: string;
      file: string;
      line?: number;
    }>;
    entities?: Array<{
      name: string;
      source?: string;
      format?: string;
      fields?: Array<{ name: string; type?: string }>;
    }>;
    relationships?: Array<{
      from: string;
      to: string;
      type?: string;
      field?: string;
      confidence?: string;
    }>;
    iac?: {
      files?: number;
      resources?: number;
      providers?: Record<string, number>;
      source_types?: Record<string, number>;
      layer_counts?: Record<string, number>;
    };
    confidence_distribution?: Record<string, number>;
    counts?: Record<string, number>;
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
    architecture_services?: string;
    architecture_code?: string;
    architecture_iac?: string;
    er: string;
    call_graph: string;
    dependencies: string;
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
  narrative?: {
    repo_summary_markdown?: string;
  };
  kiv: {
    graph_3d: string;
  };
};
