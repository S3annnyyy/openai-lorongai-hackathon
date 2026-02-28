---
name: code-autopsy
description: Perform deep architectural and risk autopsies on modern or legacy codebases. Use when Codex needs to index a large repository, build a code knowledge graph, generate architecture diagrams (Mermaid, draw.io, or Eraser-ready), simulate stress/failure scenarios, map attack surface, propose defensive patches, prioritize refactors, and forecast 2-year maintainability decay.
---

# Code Autopsy

Execute a full-system forensic pass on a repository and return a diagnostic dashboard plus action plans.

## Quick Start

Choose one input mode:
- GitHub URL mode: user pastes `https://github.com/org/repo` and run `python scripts/code_autopsy.py <url>`.
- Local workspace mode: run `python scripts/code_autopsy.py .` from the repository root in VS Code/Codex.

Both modes write outputs to `code-autopsy/.autopsy-outputs/<repo_name>/`.
GitHub URL mode does not require manual cloning; the CLI fetches source directly.

1. Build baseline artifacts:
- `repo.json`
- `graph.json`
- `metrics.json`

2. Run agent workflow in order:
- Agent 0: Coroner (orchestrator)
- Agent 1: Attacker (red team)
- Agent 2: Defender (blue team)
- Agent 3: Refactorer (surgeon)
- Agent 4: Historian (time traveler)

3. Produce dashboard artifacts:
- `attack_surface.json`
- `failure_simulation.json`
- `decay_forecast.json`
- `dashboard_state.json`

4. Export diagrams:
- `diagrams/architecture.mmd` (required)
- `diagrams/architecture.drawio` (optional)
- Eraser import payload (optional) per `references/diagram-exports.md`

## Input and Output Contract

Use `scripts/code_autopsy.py` as the default entrypoint for this skill.

CLI contract:
- positional source: GitHub URL or local repository path.
- `--output`: output base path (default `code-autopsy/.autopsy-outputs`).
- `--viewer/--no-viewer`: auto install/start viewer frontend after output (default: enabled).
- `--open-viewer/--no-open-viewer`: auto-open browser dashboard URL (default: enabled).

Default expectation for this skill:
- if `--no-viewer` and `--no-open-viewer` are not provided, the CLI should attempt to start the viewer and open the dashboard URL.

Examples:
- `python scripts/code_autopsy.py https://github.com/org/repo`
- `python scripts/code_autopsy.py .`

Output root:
- `code-autopsy/.autopsy-outputs/<repo_name>/repo.json`
- `code-autopsy/.autopsy-outputs/<repo_name>/graph.json`
- `code-autopsy/.autopsy-outputs/<repo_name>/metrics.json`
- `code-autopsy/.autopsy-outputs/<repo_name>/decay_forecast.json`
- `code-autopsy/.autopsy-outputs/<repo_name>/attack_surface.json`
- `code-autopsy/.autopsy-outputs/<repo_name>/failure_simulation.json`
- `code-autopsy/.autopsy-outputs/<repo_name>/dashboard_state.json`
- `code-autopsy/.autopsy-outputs/<repo_name>/diagrams/architecture.mmd`

## Operating Model

### Agent 0 - The Coroner (Orchestrator)

Run first. Build the body scan and scoped context for all other agents.

Required actions:
1. Inventory repository layout, language mix, entrypoints, and build system.
2. Build graph model with these edge classes:
- `imports`
- `calls`
- `owns`
- `depends_on`
- `trust_boundary_crossing`
3. Compute baseline metrics:
- Complexity proxies (function length, nesting, branching tokens)
- Coupling (fan-in, fan-out)
- Fragility (dependency concentration, optional dependency reliance)
- Churn proxies (git history when available; structural surrogates when unavailable)

Required outputs:
- `repo.json`
- `graph.json`
- `metrics.json`
- `case_file.md` (short assumptions + scope limits)

### Agent 1 - The Attacker (Red Team)

Model realistic exploitation paths from entrypoint to sink.

Look for:
- Auth/session boundaries and bypass opportunities
- Input handling hotspots (parsers, handlers, deserializers)
- Secret exposure patterns
- Dangerous sinks (`exec`, shelling out, SQL construction, file writes, SSRF vectors)
- Dependency risk patterns even without CVE calls

Required outputs:
- `attack_surface.json`
- `exploit_stories.md` (top 5 scenarios with step-by-step chain)
- `blast_radius.json`

### Agent 2 - The Defender (Blue Team)

Convert findings into practical hardening steps.

Required outputs:
- `fixes/` patch suggestions (diff-ready snippets)
- `security_posture.json` with before/after score
- `recommended_next_prs.md`

Must include:
- Quick wins
- Structural fixes
- Monitoring hooks
- Tripwire tests and CI checks

### Agent 3 - The Refactorer (Surgeon)

Prioritize maintainability impact, not aesthetic cleanup.

Target:
- Hotspots (high complexity + high coupling)
- God modules
- Cycles
- Test deserts in critical paths

Required outputs:
- `refactor_roadmap.md` (3 phases)
- `scaffolding_pr_plan.md` focused on one hotspot

### Agent 4 - The Historian (Time Traveler)

Explain architecture drift and forecast future failure points.

Required outputs:
- `evolution_narrative.md`
- `decay_forecast.json` (2-year risk by module)
- `hiring_pain_index.json`

Use git history when available. If absent, infer from structural signals and convention drift.

## Large-Repo Strategy

When repository size is large (>15k files or >2M LOC), switch to tiered indexing:
1. Tier 1: package/module graph only.
2. Tier 2: deep index only top risk modules by hotspot score.
3. Tier 3: sample leaf modules for calibration.

Always record skipped regions and confidence impact in `case_file.md`.

## Diagram Outputs

Always generate Mermaid from `graph.json`. Use:
- `scripts/render_mermaid_from_graph.py` to convert graph artifacts into flowchart syntax.

Optionally generate draw.io XML using the mapping in `references/diagram-exports.md`.

For Eraser or other diagram-as-code tools, export a normalized node/edge list plus style metadata.

## Scoring and Simulation Rules

Use scoring formulas from `references/scoring-models.md`.

For failure simulation, run at least three scenarios:
1. Traffic x10
2. Key dependency update
3. High-risk developer change in a hotspot module

Rank breakage likelihood and blast radius. Output causal chains, not only scores.

## Resources

- `references/artifacts-schema.md`: canonical output schemas.
- `references/scoring-models.md`: risk, decay, and fragility formulas.
- `references/diagram-exports.md`: Mermaid/draw.io/Eraser export expectations.
- `references/agent-prompts.md`: scoped prompts for each agent.
- `scripts/code_autopsy.py`: baseline orchestrator for GitHub URL or local path inputs.
- `scripts/render_mermaid_from_graph.py`: graph to Mermaid conversion.
- `scripts/score_decay.py`: baseline decay score calculator.
