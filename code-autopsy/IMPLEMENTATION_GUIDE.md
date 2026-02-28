# Code-Autopsy X-Ray Implementation Guide

## 1. What This Implements

`code-autopsy` runs **X-Ray mode** (MVP) for local repos and generates:
- architecture diagram
- ER diagram
- function/call graph
- module dependency graph
- onboarding map (start-here files, key flows, glossary, safe-change hints)

MVP viewer is **2D interactive** (Next.js + force graph + Mermaid tabs).
3D graph mode is **KIV / Phase 2**.

## 2. Prerequisites

Required:
- Python 3.10+
- Node.js 18+
- npm

Optional but recommended (for PNG export):
- Playwright Chromium browser

## 3. One-Time Setup (for full viewer + images)

From repo root:

```bash
cd /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/viewer
npm install
npx playwright install chromium
```

If this setup is skipped:
- analysis still runs,
- docs still generate,
- viewer uses fallback static page,
- PNG export is skipped with warning.

## 4. Main Command

From repo root:

```bash
python3 code-autopsy/scripts/code_autopsy.py <LOCAL_REPO_PATH> --mode xray --output docs --lang-hints ts,python --viewer --export-images
```

Useful flags:
- `--watch` for best-effort auto-regeneration on changes
- `--watch-interval 2.0` polling interval
- `--max-files 1200` cap indexed files

## 5. Exact Commands for Your 2 Test Repos

From repo root:

```bash
mkdir -p /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/demo-repos

# Repo 1
git clone https://github.com/digitros/nextjs-fastapi /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/demo-repos/nextjs-fastapi
python3 /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/scripts/code_autopsy.py \
  /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/demo-repos/nextjs-fastapi \
  --mode xray --output docs --lang-hints ts,python --viewer --export-images

# Repo 2
git clone https://github.com/vintasoftware/nextjs-fastapi-template /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/demo-repos/nextjs-fastapi-template
python3 /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/scripts/code_autopsy.py \
  /Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/demo-repos/nextjs-fastapi-template \
  --mode xray --output docs --lang-hints ts,python --viewer --export-images
```

## 6. What Gets Output

For each analyzed repo, default output root is:

`<target_repo>/docs/code-autopsy`

Key files:
- `repo.json`
- `graph.json`
- `metrics.json`
- `dashboard_state.json`
- `index.md`
- `case_file.md`
- `architecture.mmd`
- `er.mmd`
- `er.dbml`
- `call-graph.mmd`
- `dependencies.mmd`
- `onboarding.md`
- `top-files.md`
- `artifacts/*.json`
- `viewer-static/*` (when viewer build succeeds)
- `images/*.png` (when Playwright export succeeds)

## 7. How to Open Results

For a target repo:

```bash
cd <target_repo>/docs/code-autopsy
open index.md
open viewer-static/index.html
open images/architecture.png
```

(Use your OS-equivalent if `open` is unavailable.)

## 8. What Is Left (KIV / Phase 2)

Not in current MVP:
- 3D force graph visualization mode
- camera presets / depth clustering
- attacker / defender / refactorer / historian runtime agent workflows
- advanced draw.io / Eraser export automation beyond current references

## 9. Troubleshooting

- `Node.js not found`: install Node 18+.
- `Viewer fallback created: dependencies missing`: run `npm install` in `code-autopsy/viewer`.
- `PNG export skipped: playwright is not installed`: run `npx playwright install chromium`.
- syntax warnings in repo files: output still generated; see `case_file.md`.
