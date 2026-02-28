# Agent Prompts

Use these scoped prompts to keep each agent focused and token-efficient.

## Agent 0 - Coroner

"Build repository inventory, graph.json, and metrics.json. Record assumptions and confidence impacts. Do not produce remediation yet."

## Agent 1 - Attacker

"Starting from entrypoints and trust boundaries, enumerate exploit chains to dangerous sinks. Prioritize realistic attack stories and blast radius."

## Agent 2 - Defender

"Convert top attacker findings to patch-ready mitigations, tripwire tests, and CI guardrails. Rank by ROI and implementation effort."

## Agent 3 - Refactorer

"Select one hotspot cluster and design a low-risk, test-first refactor plan in three phases with smallest safe change surface."

## Agent 4 - Historian

"Explain architecture drift from structure (and git if available), then forecast 24-month maintainability decay with explicit drivers."
