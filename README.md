# openai-lorongai-hackathon

## Code-Autopsy X-Ray MVP

Run X-Ray mode on a local repo:

```bash
python3 code-autopsy/scripts/code_autopsy.py /path/to/repo --mode xray --output docs --viewer --export-images
```

Run autopsy + simulation (security simulation agent automatically attached):

```bash
python3 code-autopsy/scripts/code_autopsy.py <repo_or_github_url> --run-simulation
```

Notes:
- Simulation uses a 2-week iteration window by design.
- By default, up to 9 iterations will be attempted.
- No manual `--source-ref` or `--features-file` is required; the simulation engine infers features from repo signals when needed.

Default output:

`/path/to/repo/docs/code-autopsy`

Notes:
- 2D interactive Next.js viewer is MVP (`code-autopsy/viewer`).
- 3D graph mode is KIV / Phase 2.
- Watch mode is best effort (`--watch`).

## Implementation Guide

Full setup, commands, outputs, and test-repo walkthrough:

- [`code-autopsy/IMPLEMENTATION_GUIDE.md`](code-autopsy/IMPLEMENTATION_GUIDE.md)
