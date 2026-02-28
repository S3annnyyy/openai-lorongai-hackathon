# Code-Autopsy X-Ray Implementation Guide

## Main behavior

`code-autopsy/scripts/code_autopsy.py` accepts either:
- a local repository path
- a GitHub URL

Outputs are written to:
- `code-autopsy/.autopsy-outputs/<repo_name>/`

The viewer reads directly from that folder through API routes in `viewer/app/api/autopsy/*`.

## Quick run

From repo root:

```bash
python code-autopsy/scripts/code_autopsy.py https://github.com/S3annnyyy/hack-n-roll-2026
```

or

```bash
python code-autopsy/scripts/code_autopsy.py .
```

## Viewer behavior

After output generation (default):
- runs `npm install` in `code-autopsy/viewer`
- starts `npm run dev` on port `3000` if not already running
- opens `http://localhost:3000/?repo=<repo_name>`

You can disable this with:
- `--no-viewer`
- `--no-open-viewer`

## Useful flags

- `--output .autopsy-outputs` (default relative to `code-autopsy/`)
- `--viewer-port 3000`
- `--watch` (local path only)
- `--export-images`
- `--keep-clone` (for GitHub URL mode)
