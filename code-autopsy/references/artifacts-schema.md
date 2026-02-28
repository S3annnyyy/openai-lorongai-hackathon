# Artifacts Schema

Use UTF-8 JSON with stable keys and deterministic ordering when possible.

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
