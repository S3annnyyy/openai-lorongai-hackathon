# Diagram Exports

## Mermaid (required)

Produce `diagrams/architecture.mmd` using `flowchart LR`.

Node style classes:
- `critical`
- `hotspot`
- `boundary`
- `external`

Edge labels should include relation type (`calls`, `depends_on`, `trust_boundary_crossing`).

## draw.io (optional)

If requested, output `diagrams/architecture.drawio` as mxGraph XML.

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
