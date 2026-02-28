#!/usr/bin/env python3
"""Generate docs/REPORT.md from code-autopsy artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def md_cell(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip() or "_TBD_"


def join_list(values: list[Any]) -> str:
    if not values:
        return "_TBD_"
    return ", ".join(md_cell(v) for v in values)


def mermaid_block(root: Path) -> str:
    mmd_path = root / "diagrams" / "architecture.mmd"
    if mmd_path.exists():
        body = mmd_path.read_text(encoding="utf-8").rstrip()
        return f"```mermaid\n{body}\n```"
    return "_No architecture diagram found yet. Generate `diagrams/architecture.mmd` and rerun this script._"


def format_dashboard_table(state: dict[str, Any] | None) -> str:
    confidence = (state or {}).get("confidence", {})
    return "\n".join(
        [
            "| Field | Value |",
            "|---|---|",
            f'| Generated At | {md_cell((state or {}).get("generated_at", "_TBD_"))} |',
            f'| Repo | {md_cell((state or {}).get("repo", "_TBD_"))} |',
            f'| Decay Window (Months) | {md_cell((state or {}).get("decay_window_months", "_TBD_"))} |',
            f'| Graph Confidence | {md_cell(confidence.get("graph", "_TBD_"))} |',
            f'| Metrics Confidence | {md_cell(confidence.get("metrics", "_TBD_"))} |',
            f'| Attack Surface Confidence | {md_cell(confidence.get("attack_surface", "_TBD_"))} |',
            f'| Forecast Confidence | {md_cell(confidence.get("forecast", "_TBD_"))} |',
        ]
    )


def format_hotspots_table(state: dict[str, Any] | None) -> str:
    hotspots = ((state or {}).get("top_hotspots") or [])[:5]
    lines = ["| Rank | Module | Hotspot Score |", "|---|---|---|"]
    if not hotspots:
        lines.append("| 1 | _TBD_ | _TBD_ |")
        return "\n".join(lines)
    for i, row in enumerate(hotspots, start=1):
        lines.append(
            f'| {i} | {md_cell(row.get("module", "_TBD_"))} | {md_cell(row.get("hotspot_score", "_TBD_"))} |'
        )
    return "\n".join(lines)


def format_attack_paths(state: dict[str, Any] | None) -> str:
    paths = ((state or {}).get("top_attack_paths") or [])[:3]
    if not paths:
        return "\n".join(
            [
                "1. **Risk:** _TBD_  ",
                "   **Path:** _TBD_  ",
                "   **Notes:** _TBD_",
            ]
        )
    lines: list[str] = []
    for i, row in enumerate(paths, start=1):
        path_text = " -> ".join((row.get("path") or []))
        lines.extend(
            [
                f'1. **Risk:** {md_cell(row.get("risk", "_TBD_"))}  ',
                f"   **Path:** {md_cell(path_text)}  ",
                f'   **Notes:** {md_cell(row.get("notes", "_TBD_"))}',
            ]
        )
        if i != len(paths):
            lines.append("")
    return "\n".join(lines)


def format_failure_table(failure: dict[str, Any] | None) -> str:
    scenarios = (failure or {}).get("scenarios") or []
    lines = ["| Scenario | First Break Modules | Blast Radius | Confidence |", "|---|---|---|---|"]
    if not scenarios:
        lines.append("| _TBD_ | _TBD_ | _TBD_ | _TBD_ |")
        return "\n".join(lines)
    for row in scenarios:
        lines.append(
            "| "
            + f"{md_cell(row.get('name', '_TBD_'))} | "
            + f"{join_list(row.get('first_break_modules') or [])} | "
            + f"{join_list(row.get('blast_radius_nodes') or [])} | "
            + f"{md_cell(row.get('confidence', '_TBD_'))} |"
        )
    return "\n".join(lines)


def format_decay_table(decay: dict[str, Any] | None) -> str:
    forecasts = (decay or {}).get("module_forecasts") or []
    forecasts = sorted(forecasts, key=lambda x: float(x.get("decay_score", 0.0)), reverse=True)
    lines = ["| Module | Decay Score | Maintainability Risk | Drivers |", "|---|---|---|---|"]
    if not forecasts:
        lines.append("| _TBD_ | _TBD_ | _TBD_ | _TBD_ |")
        return "\n".join(lines)
    for row in forecasts[:12]:
        lines.append(
            "| "
            + f"{md_cell(row.get('module', '_TBD_'))} | "
            + f"{md_cell(row.get('decay_score', '_TBD_'))} | "
            + f"{md_cell(row.get('maintainability_risk', '_TBD_'))} | "
            + f"{join_list(row.get('drivers') or [])} |"
        )
    return "\n".join(lines)


def build_report(root: Path) -> str:
    state = load_json(root / "dashboard_state.json")
    failure = load_json(root / "failure_simulation.json")
    decay = load_json(root / "decay_forecast.json")
    diagram_section = mermaid_block(root)

    parts = [
        "# Code Autopsy Report",
        "",
        "This page is a GitHub-friendly dashboard for viewing autopsy outputs in one place.",
        "",
        "Regenerate with:",
        "",
        "```bash",
        "python3 code-autopsy/scripts/generate_report.py --root . --out docs/REPORT.md",
        "```",
        "",
        "## Quick Links",
        "",
        "- [Skill Definition](../code-autopsy/SKILL.md)",
        "- [Agent Prompts](../code-autopsy/references/agent-prompts.md)",
        "- [Artifact Schema](../code-autopsy/references/artifacts-schema.md)",
        "- [Scoring Models](../code-autopsy/references/scoring-models.md)",
        "",
        "## Architecture Diagram",
        "",
        diagram_section,
        "",
        "## Dashboard Snapshot",
        "",
        format_dashboard_table(state),
        "",
        "## Top Hotspots",
        "",
        format_hotspots_table(state),
        "",
        "## Top Attack Paths",
        "",
        format_attack_paths(state),
        "",
        "## Failure Scenarios",
        "",
        format_failure_table(failure),
        "",
        "## Decay Forecast",
        "",
        format_decay_table(decay),
        "",
        "## Raw Artifact Links",
        "",
        "- [dashboard_state.json](../dashboard_state.json)",
        "- [attack_surface.json](../attack_surface.json)",
        "- [failure_simulation.json](../failure_simulation.json)",
        "- [decay_forecast.json](../decay_forecast.json)",
        "- [metrics.json](../metrics.json)",
        "- [graph.json](../graph.json)",
        "- [repo.json](../repo.json)",
    ]

    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate docs/REPORT.md from artifacts")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--out", default="docs/REPORT.md", help="Output markdown file")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = (root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(root), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
