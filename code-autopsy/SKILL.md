---
name: code-autopsy
description: Generate Code-Autopsy X-Ray onboarding artifacts for a local repository. Use when Codex should produce architecture, ER, call, and dependency visuals; build an onboarding map; and optionally generate an interactive viewer and PNG snapshots. Trigger for commands like `/skill code-autopsy <repo> --mode xray --viewer --export-images`.
---

# Code Autopsy

Run X-Ray mode as the default workflow.

## Command

```bash
python3 scripts/code_autopsy.py <repo_path> --mode xray --output docs --viewer --export-images
```

Optional flags:
- `--watch`: best-effort watcher (manual rerun remains fallback)
- `--lang-hints ts,python`: narrow parser scope
- `--max-files 1200`: cap indexing breadth

## Required Outputs

X-Ray writes to `<repo>/docs/code-autopsy` by default:
- `repo.json`, `graph.json`, `metrics.json`, `case_file.md`
- `architecture.mmd`, `er.mmd`, `er.dbml`, `call-graph.mmd`, `dependencies.mmd`
- `onboarding.md`, `top-files.md`, `index.md`, `dashboard_state.json`
- `artifacts/*.json`
- `viewer-static/` when `--viewer` is enabled
- `images/*.png` when `--export-images` is enabled

## Operating Rules

1. Prioritize deterministic extraction and confidence labels on inferred edges.
2. Generate partial docs when signals are missing; never fail the full run for absent DB/schema/routes.
3. Keep 3D graph work out of MVP.

## KIV / Phase 2

- 3D force graph mode (Three.js / react-force-graph-3d)
- camera presets, depth clustering, and large-graph performance tuning
- attacker/defender/refactorer/historian runtime agents

## Resources

- `scripts/code_autopsy.py`: CLI runner
- `scripts/xray_core.py`: extraction + graph + render core
- `scripts/render_mermaid_from_graph.py`: graph.json -> Mermaid helper
- `scripts/score_decay.py`: 24-month decay scoring helper
- `references/artifacts-schema.md`: output schemas
- `references/diagram-exports.md`: diagram formats
- `references/scoring-models.md`: metric formulas
- `references/roadmap.md`: KIV backlog
