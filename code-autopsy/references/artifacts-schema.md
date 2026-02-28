# Artifacts Schema

Use UTF-8 JSON with stable keys and deterministic ordering when possible.

## X-Ray MVP Required Artifacts

Default output root: `code-autopsy/.autopsy-outputs/<repo_name>`

Required files:
- `repo.json`
- `graph.json`
- `metrics.json`
- `dashboard_state.json`
- `case_file.md`
- `architecture.mmd`
- `er.mmd`
- `er.dbml`
- `call-graph.mmd`
- `dependencies.mmd`
- `onboarding.md`
- `top-files.md`
- `index.md`
- `artifacts/entrypoints.json`
- `artifacts/routes.json`
- `artifacts/models.json`
- `artifacts/imports.json`
- `artifacts/calls.json`
- `artifacts/entities.json`
- `artifacts/cycles.json`
- `artifacts/hotspots.json`
- `artifacts/glossary.json`

Optional files:
- `images/*.png` (when `--export-images` succeeds)

## dashboard_state.json

{
  "generated_at": "string",
  "summary": {},
  "graphs": {},
  "diagrams": {},
  "onboarding": {},
  "kiv": {
    "graph_3d": "Deferred to Phase 2"
  }
}

## repo.json

{
  "name": "string",
  "root": "string",
  "languages": ["string"],
  "frameworks": ["string"],
  "entrypoints": ["string"],
  "indexing": {
    "strategy": "full|tiered",
    "files_indexed": 0,
    "files_skipped": 0
  }
}

## graph.json

{
  "nodes": [
    {
      "id": "module:path-or-symbol",
      "type": "package|module|class|function|service|datastore|external",
      "label": "string",
      "owner": "string|null",
      "criticality": 0.0
    }
  ],
  "edges": [
    {
      "from": "node-id",
      "to": "node-id",
      "type": "imports|calls|depends_on|trust_boundary_crossing|reads|writes",
      "weight": 1.0
    }
  ]
}

## metrics.json

{
  "module_metrics": [
    {
      "module": "string",
      "complexity": 0.0,
      "coupling_in": 0,
      "coupling_out": 0,
      "test_coverage_proxy": 0.0,
      "ownership_risk": 0.0,
      "dependency_fragility": 0.0,
      "hotspot_score": 0.0
    }
  ]
}

## attack_surface.json

{
  "entrypoints": ["string"],
  "trust_boundaries": ["string"],
  "sinks": ["string"],
  "critical_paths": [
    {
      "path": ["node-id"],
      "risk": 0.0,
      "notes": "string"
    }
  ]
}

> Note: `attack_surface.json`, `failure_simulation.json`, and other attacker/defender/refactorer/historian artifacts are Phase 2 (KIV), not part of X-Ray MVP execution.

## failure_simulation.json

{
  "scenarios": [
    {
      "name": "traffic_x10|dep_update|hotspot_change",
      "first_break_modules": ["string"],
      "blast_radius_nodes": ["node-id"],
      "confidence": 0.0,
      "causal_chain": ["string"]
    }
  ]
}

## decay_forecast.json

{
  "window_months": 24,
  "module_forecasts": [
    {
      "module": "string",
      "decay_score": 0.0,
      "drivers": ["complexity", "coupling", "ownership_risk", "test_desert"],
      "maintainability_risk": "low|medium|high|critical"
    }
  ]
}
