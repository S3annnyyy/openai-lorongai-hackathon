# Diagram Exports

## Mermaid (required)

Produce these files at output root:
- `architecture.mmd` using `flowchart LR`
- `er.mmd` using `erDiagram`
- `call-graph.mmd` using `flowchart LR`
- `dependencies.mmd` using `flowchart LR`
- `sequence.mmd` using `sequenceDiagram`
- `use-case.mmd` using `flowchart LR`

Node style classes:
- `critical`
- `hotspot`
- `boundary`
- `external`

Edge labels should include relation type (`calls`, `depends_on`, `trust_boundary_crossing`).

## PlantUML (required)

Produce these files at output root:
- `architecture.puml` using component diagram syntax (`@startuml ... @enduml`)
- `er.puml` using class/ER-friendly syntax
- `call-graph.puml` using component graph syntax
- `dependencies.puml` using component graph syntax
- `sequence.puml` using sequence diagram syntax
- `use-case.puml` using use case diagram syntax
- `json-data.puml` using `@startjson ... @endjson`
- `yaml-data.puml` using `@startyaml ... @endyaml`

Conventions:
- include `left to right direction`
- use deterministic aliases for nodes
- edge labels should include relation type and optional confidence suffix

## draw.io (optional)

If requested, output `architecture.drawio` as mxGraph XML.
If Terraform is detected, also output `terraform-architecture.drawio` to visualize IaC cloud topology.

Minimum metadata per shape:
- id
- label
- type
- risk score

## Eraser/diagram-as-code (optional)

Export normalized graph payload:

{
  "nodes": [{"id":"...","label":"...","kind":"module","risk":0.72}],
  "edges": [{"from":"...","to":"...","type":"calls","weight":1.0}],
  "styles": {"hotspotThreshold":0.65}
}

Use this payload as input to platform-specific renderers.

## Viewer Rendering

- MVP viewer is 2D interactive graph + Mermaid tabs (architecture/ER/call/dependencies/sequence/use-case) + JSON/YAML data docs.
- 3D force graph export/rendering is KIV (Phase 2).
