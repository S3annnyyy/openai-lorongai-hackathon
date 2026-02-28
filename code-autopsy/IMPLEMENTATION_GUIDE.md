# Code-Autopsy Implementation Guide

## Install as a Codex skill (one-time)

### Option A: local dev install (symlink)

From this repository root:

```bash
bash code-autopsy/scripts/install_skill_local.sh
```

This links the skill to `~/.codex/skills/code-autopsy` (or `$CODEX_HOME/skills/code-autopsy`).

### Option B: install from GitHub (for other users)

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo <owner>/<repo> \
  --path code-autopsy
```

After installing, restart Codex so `$code-autopsy` is available in new sessions.

## CLI behavior (current on `main`)

`code-autopsy/scripts/code_autopsy.py` accepts:
- local repository path
- GitHub URL (`https://github.com/<owner>/<repo>` and `.../tree/<ref>` forms)

For GitHub URLs:
- no manual clone is required
- the CLI first tries downloading a GitHub source archive
- if archive download fails, it falls back to shallow `git clone --depth 1`

Default output root is:
- `code-autopsy/.autopsy-outputs/<repo_name>/`

Notes:
- `--output` values that are not absolute paths are resolved relative to `code-autopsy/` (skill root), not the shell CWD.
- temporary GitHub source checkouts live under `code-autopsy/.autopsy-outputs/_sources/` unless `--keep-clone` is omitted (default cleanup).

The viewer reads output through:
- `code-autopsy/viewer/app/api/autopsy/route.ts` (repo list)
- `code-autopsy/viewer/app/api/autopsy/[repo]/route.ts` (repo dashboard payload)

## Quick run

From workspace root:

```bash
python3 code-autopsy/scripts/code_autopsy.py .
```

Run with simulation attached:

```bash
python3 code-autopsy/scripts/code_autopsy.py https://github.com/org/repo --run-simulation
```

Simulation defaults used by this integration:

- `--max-iterations` default is `9`
- simulation window is `--weeks-per-iteration 2`
- no explicit `--iteration-command` required; `simulate_agent.py` handles feature execution policy itself

Or GitHub URL mode:

```bash
python3 code-autopsy/scripts/code_autopsy.py https://github.com/org/repo
```

Generation only (skip viewer install/start/browser open):

```bash
python3 code-autopsy/scripts/code_autopsy.py <source> --no-viewer --no-open-viewer
```

## Viewer behavior (default)

With default flags, CLI will:
- run `npm install` in `code-autopsy/viewer`
- start `npm run dev -- --port <viewer-port>` if that port is not already in use
- set `AUTOPSY_OUTPUT_ROOT` for viewer API routes
- open `http://localhost:<port>/?repo=<repo_name>&tab=architecture_services`
- fail fast (non-zero exit) if viewer install/start/browser-open fails
- launch viewer in a detached session so it remains available after CLI exit
- resolve `npm`/`node` from PATH, then from the current login shell; optional overrides:
  - `AUTOPSY_NPM_BIN=/absolute/path/to/npm`
  - `AUTOPSY_NODE_BIN=/absolute/path/to/node`
- data-diagram renderer uses PlantUML server (default `https://www.plantuml.com/plantuml`);
  viewer proxies rendering through `/api/plantuml` (POST)
  override server with `PLANTUML_SERVER_URL` (or `NEXT_PUBLIC_PLANTUML_SERVER_URL`)

Defaults:
- `--viewer` enabled
- `--open-viewer` enabled
- `--viewer-port 3000`

Disable with:
- `--no-viewer`
- `--no-open-viewer`

## Important flags

- `--output .autopsy-outputs` (resolved to `code-autopsy/.autopsy-outputs`)
- `--viewer/--no-viewer`
- `--open-viewer/--no-open-viewer`
- `--viewer-port 3000`
- `--watch` (local paths only; GitHub URLs are rejected)
- `--watch-interval 2.0`
- `--export-images`
- `--keep-clone` (keep downloaded/cloned GitHub temp source)
- `--lang-hints ts,python`
- `--max-files 1200`

## Output contract (current X-Ray MVP)

Per repo output root (`code-autopsy/.autopsy-outputs/<repo_name>/`):
- `repo.json`
- `graph.json`
- `metrics.json`
- `dashboard_state.json`
- `index.md`
- `handoff.md`
- `onboarding.md`
- `repo-summary.md`
- `top-files.md`
- `case_file.md`
- `architecture-services.mmd`
- `architecture-code.mmd`
- `architecture-iac.mmd`
- `architecture.mmd` (legacy alias to services-level architecture)
- `architecture-services.puml`
- `architecture-code.puml`
- `architecture-iac.puml`
- `architecture.puml` (legacy alias to services-level architecture)
- `er.mmd`
- `er.puml`
- `er.dbml`
- `call-graph.mmd`
- `call-graph.puml`
- `dependencies.mmd`
- `dependencies.puml`
- `sequence.mmd`
- `sequence.puml`
- `use-case.mmd`
- `use-case.puml`
- `data.json`
- `data.yaml`
- `json-data.puml`
- `yaml-data.puml`
- `artifacts/*.json` (`entrypoints`, `routes`, `models`, `imports`, `calls`, `entities`, `iac`, `cycles`, `hotspots`, `glossary`)
- `diagrams/*.mmd` (duplicated copies for architecture/ER/call/dependencies/sequence/use-case)
- `diagrams/*.puml` (duplicated PlantUML copies for architecture/ER/call/dependencies/sequence/use-case/json-data/yaml-data)
- `images/*.png` (only when `--export-images` succeeds)

`dashboard_state.json` now includes:
- `diagrams` (Mermaid sources plus JSON/YAML data docs used by viewer)
- `diagrams_plantuml` (parallel PlantUML sources for architecture/ER/call/dependencies/sequence/use-case/json-data/yaml-data)
- `summary.repo_root` (stable source reference for local path or GitHub URL input)
- `summary.analysis_workspace` (actual filesystem path analyzed for this run)

## Diagram levels

- `Architecture (Services)`: high-level service/system view (default architecture view in viewer)
- `Architecture (Code)`: code-layer relationships
- `Architecture (IaC)`: infrastructure/IaC-layer view from Terraform/Kubernetes/Compose/CloudFormation/Bicep-like files
- `Sequence`: request/handler/data interaction flows inferred from routes + calls
- `Use Case`: endpoint-centric capability map
- `JSON Data` and `YAML Data`: normalized analysis snapshot documents
  - viewer renders these as PlantUML diagrams (with raw source fallback)

## Smoke test repos

```bash
mkdir -p /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/demo-repos

# 1) digitros/nextjs-fastapi
python3 /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/scripts/code_autopsy.py \
  https://github.com/digitros/nextjs-fastapi

# 2) vintasoftware/nextjs-fastapi-template
python3 /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/scripts/code_autopsy.py \
  https://github.com/vintasoftware/nextjs-fastapi-template
```

## Manual viewer run (optional)

```bash
cd code-autopsy/viewer
AUTOPSY_OUTPUT_ROOT=/Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/.autopsy-outputs npm run dev -- --port 3000
# if Next dev cache is stale, use:
AUTOPSY_OUTPUT_ROOT=/Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/.autopsy-outputs npm run dev:clean -- --port 3000
```

Open `http://localhost:3000/?repo=<repo_name>&tab=architecture_services`.

## Render PlantUML diagrams (optional)

If PlantUML is installed locally, render the generated `.puml` files to SVG/PNG:

```bash
java -jar plantuml.jar -tsvg /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/.autopsy-outputs/<repo_name>/diagrams/*.puml
```

## Troubleshooting

- `No autopsy output found`: verify artifacts exist at `code-autopsy/.autopsy-outputs/<repo>/`.
- viewer repo 404: verify `<repo>/dashboard_state.json` exists.
- `Cannot find module './9276.js'` (or similar chunk IDs): stale Next build cache. Run:
  - `cd code-autopsy/viewer && rm -rf .next && AUTOPSY_OUTPUT_ROOT=... npm run dev -- --port 3000`
  - or `AUTOPSY_OUTPUT_ROOT=... npm run dev:clean -- --port 3000`
- `Error: watch mode is only supported for local repository paths.`: remove `--watch` when source is a GitHub URL.
- `Viewer dependency install failed: npm not found`: install Node.js/npm and re-run.
- `PNG export skipped`: install Playwright browser:
  - `cd code-autopsy/viewer && npx playwright install chromium`
- Mermaid parse issues caused by escaped text (`flowchart LR\n...`): now handled in viewer; if it persists, regenerate artifacts with latest backend code.
