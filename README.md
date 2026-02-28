# openai-lorongai-hackathon

## Code-Autopsy X-Ray MVP

Run X-Ray mode on a local repo:

```bash
python3 code-autopsy/scripts/code_autopsy.py /path/to/repo --mode xray --output docs --viewer --export-images
```

Default output:

`/path/to/repo/docs/code-autopsy`

Notes:
- 2D interactive Next.js viewer is MVP (`code-autopsy/viewer`).
- 3D graph mode is KIV / Phase 2.
- Watch mode is best effort (`--watch`).

## Implementation Guide

Full setup, commands, outputs, and test-repo walkthrough:

- [`code-autopsy/IMPLEMENTATION_GUIDE.md`](/Users/kaelanwan/Documents/Projects/openai-lorongai-hackathon/code-autopsy/IMPLEMENTATION_GUIDE.md)
