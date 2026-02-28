#!/usr/bin/env python3
"""Convert graph.json into a PlantUML component diagram."""

import argparse
import json
import re
from pathlib import Path


def sanitize(node_id: str) -> str:
    return "n_" + re.sub(r"[^a-zA-Z0-9_]", "_", node_id)


def short(label: str, max_len: int = 36) -> str:
    return label if len(label) <= max_len else label[: max_len - 3] + "..."


def safe_text(value: str) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ").replace('"', "'")
    return re.sub(r"\s+", " ", text).strip()


def edge_label(edge_type: str, confidence: str | None = None) -> str:
    etype = re.sub(r"[^a-zA-Z0-9]+", "_", str(edge_type or "rel")).strip("_").lower()
    conf = re.sub(r"[^a-zA-Z0-9]+", "_", str(confidence or "")).strip("_").lower()
    return f"{etype}_{conf}" if conf else etype


def render(graph: dict) -> str:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    lines = [
        "@startuml",
        "left to right direction",
        "skinparam componentStyle rectangle",
        "skinparam component<<external>> {",
        "  BackgroundColor #94a3b8",
        "  BorderColor #334155",
        "}",
    ]
    declared = set()

    for node in nodes:
        nid = str(node.get("id", ""))
        alias = sanitize(nid)
        if alias in declared:
            continue
        declared.add(alias)
        label = short(safe_text(node.get("label") or nid or "unknown"))
        stereotype = " <<external>>" if str(node.get("type", "")) == "external" else ""
        lines.append(f'component "{label}" as {alias}{stereotype}')

    for edge in edges:
        src = sanitize(str(edge.get("from", "")))
        dst = sanitize(str(edge.get("to", "")))
        label = edge_label(str(edge.get("type", "rel")), edge.get("confidence"))
        lines.append(f"{src} --> {dst} : {label}")

    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render PlantUML from graph.json")
    parser.add_argument("--graph", required=True, help="Path to graph.json")
    parser.add_argument("--out", required=True, help="Path to output .puml")
    args = parser.parse_args()

    graph_path = Path(args.graph)
    out_path = Path(args.out)

    with graph_path.open("r", encoding="utf-8") as handle:
        graph = json.load(handle)

    puml = render(graph)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(puml, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
