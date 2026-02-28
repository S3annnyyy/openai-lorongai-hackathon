# Code Autopsy Report

This page is a GitHub-friendly dashboard for viewing autopsy outputs in one place.

Regenerate with:

```bash
python3 code-autopsy/scripts/generate_report.py --root . --out docs/REPORT.md
```

## Quick Links

- [Skill Definition](../code-autopsy/SKILL.md)
- [Agent Prompts](../code-autopsy/references/agent-prompts.md)
- [Artifact Schema](../code-autopsy/references/artifacts-schema.md)
- [Scoring Models](../code-autopsy/references/scoring-models.md)

## Architecture Diagram

```mermaid
flowchart LR
    n_external_cli_user_input["CLI User Input"]
    n_external_filesystem["Local Filesystem"]
    n_external_py_argparse["python:argparse"]
    n_external_py_json["python:json"]
    n_external_py_pathlib["python:pathlib"]
    n_function_code_autopsy_scripts_render_mermaid_from_graph_py_main["render_mermaid_from_graph.py:main"]
    n_function_code_autopsy_scripts_render_mermaid_from_graph_py_render["render_mermaid_from_graph.py:render"]
    n_function_code_autopsy_scripts_render_mermaid_from_graph_py_sanitize["render_mermaid_from_graph.py:sani..."]
    n_function_code_autopsy_scripts_render_mermaid_from_graph_py_short["render_mermaid_from_graph.py:short"]
    n_function_code_autopsy_scripts_score_decay_py_band["score_decay.py:band"]
    n_function_code_autopsy_scripts_score_decay_py_clamp["score_decay.py:clamp"]
    n_function_code_autopsy_scripts_score_decay_py_compute["score_decay.py:compute"]
    n_function_code_autopsy_scripts_score_decay_py_main["score_decay.py:main"]
    n_module_README_md["README.md"]
    n_module_code_autopsy_SKILL_md["SKILL.md"]
    n_module_code_autopsy_agents_openai_yaml["openai.yaml"]
    n_module_code_autopsy_references_agent_prompts_md["agent-prompts.md"]
    n_module_code_autopsy_references_artifacts_schema_md["artifacts-schema.md"]
    n_module_code_autopsy_references_diagram_exports_md["diagram-exports.md"]
    n_module_code_autopsy_references_scoring_models_md["scoring-models.md"]
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py["render_mermaid_from_graph.py"]
    n_module_code_autopsy_scripts_score_decay_py["score_decay.py"]
    n_function_code_autopsy_scripts_render_mermaid_from_graph_py_main -->|calls| n_function_code_autopsy_scripts_render_mermaid_from_graph_py_render
    n_function_code_autopsy_scripts_render_mermaid_from_graph_py_render -->|calls| n_function_code_autopsy_scripts_render_mermaid_from_graph_py_sanitize
    n_function_code_autopsy_scripts_render_mermaid_from_graph_py_render -->|calls| n_function_code_autopsy_scripts_render_mermaid_from_graph_py_short
    n_function_code_autopsy_scripts_score_decay_py_compute -->|calls| n_function_code_autopsy_scripts_score_decay_py_clamp
    n_function_code_autopsy_scripts_score_decay_py_main -->|calls| n_function_code_autopsy_scripts_score_decay_py_band
    n_function_code_autopsy_scripts_score_decay_py_main -->|calls| n_function_code_autopsy_scripts_score_decay_py_compute
    n_module_code_autopsy_SKILL_md -->|depends_on| n_module_code_autopsy_references_agent_prompts_md
    n_module_code_autopsy_SKILL_md -->|depends_on| n_module_code_autopsy_references_artifacts_schema_md
    n_module_code_autopsy_SKILL_md -->|depends_on| n_module_code_autopsy_references_diagram_exports_md
    n_module_code_autopsy_SKILL_md -->|depends_on| n_module_code_autopsy_references_scoring_models_md
    n_module_code_autopsy_SKILL_md -->|depends_on| n_module_code_autopsy_scripts_render_mermaid_from_graph_py
    n_module_code_autopsy_SKILL_md -->|depends_on| n_module_code_autopsy_scripts_score_decay_py
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|trust_boundary_crossing| n_external_cli_user_input
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|calls| n_external_filesystem
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|trust_boundary_crossing| n_external_filesystem
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|depends_on| n_external_py_argparse
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|imports| n_external_py_argparse
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|depends_on| n_external_py_json
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|imports| n_external_py_json
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|depends_on| n_external_py_pathlib
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|imports| n_external_py_pathlib
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|owns| n_function_code_autopsy_scripts_render_mermaid_from_graph_py_main
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|owns| n_function_code_autopsy_scripts_render_mermaid_from_graph_py_render
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|owns| n_function_code_autopsy_scripts_render_mermaid_from_graph_py_sanitize
    n_module_code_autopsy_scripts_render_mermaid_from_graph_py -->|owns| n_function_code_autopsy_scripts_render_mermaid_from_graph_py_short
    n_module_code_autopsy_scripts_score_decay_py -->|trust_boundary_crossing| n_external_cli_user_input
    n_module_code_autopsy_scripts_score_decay_py -->|calls| n_external_filesystem
    n_module_code_autopsy_scripts_score_decay_py -->|trust_boundary_crossing| n_external_filesystem
    n_module_code_autopsy_scripts_score_decay_py -->|depends_on| n_external_py_argparse
    n_module_code_autopsy_scripts_score_decay_py -->|imports| n_external_py_argparse
    n_module_code_autopsy_scripts_score_decay_py -->|depends_on| n_external_py_json
    n_module_code_autopsy_scripts_score_decay_py -->|imports| n_external_py_json
    n_module_code_autopsy_scripts_score_decay_py -->|depends_on| n_external_py_pathlib
    n_module_code_autopsy_scripts_score_decay_py -->|imports| n_external_py_pathlib
    n_module_code_autopsy_scripts_score_decay_py -->|owns| n_function_code_autopsy_scripts_score_decay_py_band
    n_module_code_autopsy_scripts_score_decay_py -->|owns| n_function_code_autopsy_scripts_score_decay_py_clamp
    n_module_code_autopsy_scripts_score_decay_py -->|owns| n_function_code_autopsy_scripts_score_decay_py_compute
    n_module_code_autopsy_scripts_score_decay_py -->|owns| n_function_code_autopsy_scripts_score_decay_py_main
    classDef critical fill:#f87171,stroke:#7f1d1d,color:#111827;
    classDef normal fill:#93c5fd,stroke:#1e3a8a,color:#111827;
    class n_external_cli_user_input critical;
    class n_external_filesystem critical;
    class n_external_py_argparse normal;
    class n_external_py_json normal;
    class n_external_py_pathlib normal;
    class n_function_code_autopsy_scripts_render_mermaid_from_graph_py_main normal;
    class n_function_code_autopsy_scripts_render_mermaid_from_graph_py_render normal;
    class n_function_code_autopsy_scripts_render_mermaid_from_graph_py_sanitize normal;
    class n_function_code_autopsy_scripts_render_mermaid_from_graph_py_short normal;
    class n_function_code_autopsy_scripts_score_decay_py_band normal;
    class n_function_code_autopsy_scripts_score_decay_py_clamp normal;
    class n_function_code_autopsy_scripts_score_decay_py_compute normal;
    class n_function_code_autopsy_scripts_score_decay_py_main normal;
    class n_module_README_md normal;
    class n_module_code_autopsy_SKILL_md normal;
    class n_module_code_autopsy_agents_openai_yaml normal;
    class n_module_code_autopsy_references_agent_prompts_md normal;
    class n_module_code_autopsy_references_artifacts_schema_md normal;
    class n_module_code_autopsy_references_diagram_exports_md normal;
    class n_module_code_autopsy_references_scoring_models_md normal;
    class n_module_code_autopsy_scripts_render_mermaid_from_graph_py normal;
    class n_module_code_autopsy_scripts_score_decay_py normal;
```

## Dashboard Snapshot

| Field | Value |
|---|---|
| Generated At | 2026-02-28T03:52:45Z |
| Repo | openai-lorongai-hackathon |
| Decay Window (Months) | 24 |
| Graph Confidence | 0.87 |
| Metrics Confidence | 0.78 |
| Attack Surface Confidence | 0.66 |
| Forecast Confidence | 0.74 |

## Top Hotspots

| Rank | Module | Hotspot Score |
|---|---|---|
| 1 | code-autopsy/scripts/render_mermaid_from_graph.py | 0.5209 |
| 2 | code-autopsy/scripts/score_decay.py | 0.4863 |
| 3 | code-autopsy/SKILL.md | 0.3826 |
| 4 | code-autopsy/references/artifacts-schema.md | 0.1687 |
| 5 | code-autopsy/references/diagram-exports.md | 0.1477 |

## Top Attack Paths

1. **Risk:** 0.58  
   **Path:** module:code-autopsy/SKILL.md -> module:code-autopsy/scripts/render_mermaid_from_graph.py -> external:filesystem  
   **Notes:** Untrusted graph.json can expand diagram size and drive oversized output writes.

1. **Risk:** 0.54  
   **Path:** module:code-autopsy/SKILL.md -> module:code-autopsy/scripts/score_decay.py -> external:filesystem  
   **Notes:** CLI-controlled metrics path crosses trust boundary to local file read/write.

1. **Risk:** 0.36  
   **Path:** module:code-autopsy/agents/openai.yaml -> module:code-autopsy/SKILL.md -> module:code-autopsy/references/artifacts-schema.md  
   **Notes:** Prompt/reference tampering can steer generated artifacts and reduce assurance.

## Failure Scenarios

| Scenario | First Break Modules | Blast Radius | Confidence |
|---|---|---|---|
| traffic_x10 | code-autopsy/scripts/render_mermaid_from_graph.py | module:code-autopsy/scripts/render_mermaid_from_graph.py, external:filesystem | 0.71 |
| dep_update | code-autopsy/scripts/score_decay.py | module:code-autopsy/scripts/score_decay.py, module:code-autopsy/references/scoring-models.md | 0.62 |
| hotspot_change | code-autopsy/SKILL.md, code-autopsy/scripts/render_mermaid_from_graph.py | module:code-autopsy/SKILL.md, module:code-autopsy/scripts/render_mermaid_from_graph.py, module:code-autopsy/references/artifacts-schema.md | 0.68 |

## Decay Forecast

| Module | Decay Score | Maintainability Risk | Drivers |
|---|---|---|---|
| code-autopsy/scripts/render_mermaid_from_graph.py | 0.4957 | medium | complexity, coupling, ownership_risk, test_desert |
| code-autopsy/scripts/score_decay.py | 0.4661 | medium | complexity, coupling, ownership_risk, test_desert |
| code-autopsy/SKILL.md | 0.4338 | medium | complexity, coupling, ownership_risk, test_desert |
| code-autopsy/references/artifacts-schema.md | 0.3165 | medium | complexity, coupling, ownership_risk, test_desert |
| code-autopsy/references/diagram-exports.md | 0.2985 | low | complexity, coupling, ownership_risk, test_desert |
| code-autopsy/references/scoring-models.md | 0.2969 | low | complexity, coupling, ownership_risk, test_desert |
| code-autopsy/references/agent-prompts.md | 0.2857 | low | complexity, coupling, ownership_risk, test_desert |
| code-autopsy/agents/openai.yaml | 0.272 | low | complexity, coupling, ownership_risk, test_desert |
| README.md | 0.266 | low | complexity, coupling, ownership_risk, test_desert |

## Raw Artifact Links

- [dashboard_state.json](../dashboard_state.json)
- [attack_surface.json](../attack_surface.json)
- [failure_simulation.json](../failure_simulation.json)
- [decay_forecast.json](../decay_forecast.json)
- [metrics.json](../metrics.json)
- [graph.json](../graph.json)
- [repo.json](../repo.json)
