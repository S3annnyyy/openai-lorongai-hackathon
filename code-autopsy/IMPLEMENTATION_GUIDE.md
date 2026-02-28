# Code-Autopsy Implementation Guide

## Install as a Codex skill (one-time)

### Option A: local dev install (symlink)

From this repository root:

```bash
bash code-autopsy/scripts/install_skill_local.sh
```

This links the skill to:
- `~/.codex/skills/code-autopsy` (or `$CODEX_HOME/skills/code-autopsy`).

### Option B: install from GitHub (for other users)

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo <owner>/<repo> \
  --path code-autopsy
```

After installing, restart Codex so `$code-autopsy` is available in new sessions.

## Main behavior

`code-autopsy/scripts/code_autopsy.py` now accepts:
- a local repository path
- a GitHub URL

For GitHub URLs:
- no manual clone is required
- CLI fetches a source archive directly from GitHub by default
- only if archive fetch fails, it falls back to shallow `git clone`

Artifacts are generated under:
- `code-autopsy/.autopsy-outputs/<repo_name>/`

The viewer reads this output through API routes:
- `viewer/app/api/autopsy/route.ts` (repo list)
- `viewer/app/api/autopsy/[repo]/route.ts` (repo dashboard payload)

## Quick run

From workspace root:

```bash
python3 code-autopsy/scripts/code_autopsy.py .
```

Or GitHub URL mode:

```bash
python3 code-autopsy/scripts/code_autopsy.py https://github.com/org/repo
```

## Viewer behavior (main-default)

By default, CLI will:
- run `npm install` in `code-autopsy/viewer`
- start `npm run dev` on `--viewer-port` (default `3000`) if not already running
- open `http://localhost:<port>/?repo=<repo_name>`

This means viewer auto-launch is enabled by default in main flow.

Disable auto viewer launch with:
- `--no-viewer`
- `--no-open-viewer`

## Important flags

- `--output .autopsy-outputs` (default, relative to `code-autopsy/`)
- `--viewer/--no-viewer`
- `--open-viewer/--no-open-viewer`
- `--viewer-port 3000`
- `--watch` (local paths only)
- `--export-images`
- `--keep-clone` (keep temporary downloaded/cloned GitHub source)
- `--lang-hints ts,python`
- `--max-files 1200`

## Output contract (current)

Per repo output root:
- `repo.json`
- `graph.json`
- `metrics.json`
- `dashboard_state.json`
- `onboarding.md`
- `top-files.md`
- `case_file.md`
- `repo-summary.md`
- `architecture.mmd` (legacy alias; currently services-level)
- `architecture-services.mmd` (high-level service/microservices architecture)
- `architecture-code.mmd` (code architecture)
- `architecture-iac.mmd` (IaC architecture)
- `er.mmd`
- `er.dbml`
- `call-graph.mmd`
- `dependencies.mmd`
- `artifacts/*.json` (includes `iac.json`)
- `images/*.png` (when `--export-images` succeeds)

## Diagram levels

You now get 3 architecture perspectives:
- `Architecture (Services)`: high-level system design / microservices-style view (default in viewer)
- `Architecture (Code)`: deeper code-level architectural relationships
- `Architecture (IaC)`: infra/IaC-derived architecture view (Terraform/K8s/Compose/CFN/Bicep when detected)

## Testing your two repos

```bash
mkdir -p /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/demo-repos

# 1) digitros/nextjs-fastapi
python3 /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/scripts/code_autopsy.py \
  https://github.com/digitros/nextjs-fastapi

# 2) vintasoftware/nextjs-fastapi-template
python3 /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/scripts/code_autopsy.py \
  https://github.com/vintasoftware/nextjs-fastapi-template
```

If you only want generation (no viewer auto-run):

```bash
python3 code-autopsy/scripts/code_autopsy.py <source> --no-viewer --no-open-viewer
```

## Manual viewer run (optional)

```bash
cd code-autopsy/viewer
AUTOPSY_OUTPUT_ROOT=/Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/.autopsy-outputs npm run dev -- --port 3000
```

Open:
- `http://localhost:3000/?repo=<repo_name>`

## Troubleshooting

- `No autopsy output found`: ensure artifacts exist under `code-autopsy/.autopsy-outputs/<repo>/`.
- Viewer 404 for repo dashboard: verify `dashboard_state.json` exists in that repo output folder.
- Mermaid parse errors: rerun CLI with latest backend so sanitized labels are regenerated.
- Graph appears disconnected: ensure output is regenerated after code changes; viewer reads API-backed dashboard state.
- `PNG export skipped`: install Playwright browser in viewer:
  - `cd code-autopsy/viewer && npx playwright install chromium`
