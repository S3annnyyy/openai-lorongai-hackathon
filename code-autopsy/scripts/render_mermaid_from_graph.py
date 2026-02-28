#!/usr/bin/env python3
"""Convert graph.json into a Mermaid flowchart."""

import argparse
import json
from pathlib import Path


def sanitize(node_id: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in node_id)


def short(label: str, max_len: int = 36) -> str:
    return label if len(label) <= max_len else label[: max_len - 3] + "..."


def render(graph: dict) -> str:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    lines = ["flowchart LR"]
    risk = {}

    for node in nodes:
      nid = node.get("id", "")
      sid = sanitize(nid)
      label = short(node.get("label") or nid or "unknown")
      lines.append(f"    {sid}[\"{label}\"]")
      risk[sid] = float(node.get("criticality", 0.0) or 0.0)

    for edge in edges:
      src = sanitize(edge.get("from", ""))
      dst = sanitize(edge.get("to", ""))
      etype = edge.get("type", "rel")
      lines.append(f"    {src} -->|{etype}| {dst}")

    lines.extend(
        [
            "    classDef critical fill:#f87171,stroke:#7f1d1d,color:#111827;",
            "    classDef normal fill:#93c5fd,stroke:#1e3a8a,color:#111827;",
        ]
    )

    for sid, score in risk.items():
      class_name = "critical" if score >= 0.7 else "normal"
      lines.append(f"    class {sid} {class_name};")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Mermaid from graph.json")
    parser.add_argument("--graph", required=True, help="Path to graph.json")
    parser.add_argument("--out", required=True, help="Path to output .mmd")
    args = parser.parse_args()

    graph_path = Path(args.graph)
    out_path = Path(args.out)

    with graph_path.open("r", encoding="utf-8") as f:
      graph = json.load(f)

    mmd = render(graph)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(mmd, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
