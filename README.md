# openai-lorongai-hackathon

## Code-Autopsy X-Ray MVP

`code-autopsy` analyzes a local repo path or GitHub URL and generates:
- architecture diagrams (services, code, IaC)
- ER + DBML schema views
- dependency graph + call graph
- onboarding docs (`index`, start-here, summary, top files, case file)
- interactive Next.js dashboard viewer (2D; 3D is KIV/Phase 2)

## Install skill (one-time)

Local install (from this repo):

```bash
bash code-autopsy/scripts/install_skill_local.sh
```

Install directly from GitHub:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo S3annnyyy/openai-lorongai-hackathon \
  --path code-autopsy
```

Restart Codex after installation.

## Quick run

Local repo path:

```bash
python3 code-autopsy/scripts/code_autopsy.py /path/to/repo
```

GitHub URL:

```bash
python3 code-autopsy/scripts/code_autopsy.py https://github.com/org/repo
```

Generation only (no viewer install/start/open):

```bash
python3 code-autopsy/scripts/code_autopsy.py <source> --no-viewer --no-open-viewer
```

## Current defaults on `main`

- output root: `code-autopsy/.autopsy-outputs/<repo_name>/`
- viewer auto-launch: enabled
- browser open: enabled
- viewer URL: `http://localhost:3000/?repo=<repo_name>`

## Output snapshot

```text
code-autopsy/.autopsy-outputs/<repo_name>/
  repo.json
  graph.json
  metrics.json
  dashboard_state.json
  index.md
  onboarding.md
  repo-summary.md
  top-files.md
  case_file.md
  architecture-services.mmd
  architecture-code.mmd
  architecture-iac.mmd
  architecture.mmd
  er.mmd
  er.dbml
  call-graph.mmd
  dependencies.mmd
  artifacts/*.json
  diagrams/*.mmd
  images/*.png            # only with --export-images
```

Notes:
- viewer app is in `code-autopsy/viewer`
- watch mode is best effort and local-path only (`--watch`)
- GitHub URL mode downloads source automatically (fallbacks to shallow clone if needed)

## Implementation guide

Full setup and operational details:

- [`code-autopsy/IMPLEMENTATION_GUIDE.md`](code-autopsy/IMPLEMENTATION_GUIDE.md)
