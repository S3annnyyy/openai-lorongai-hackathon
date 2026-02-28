# Multi-Agent Simulation Context: Security-Resilience Sprint

## Scenario framing
- Program length: 12 weeks (3 months).
- Iteration duration: 2 weeks.
- Iteration count for 12 weeks: 6.
- This file defines the expected behavior of support agents for every simulation iteration.

## Agent 1 - Red Team (Attacker)
- Primary task: identify exploitability and abuse paths.
- Deliverables:
  - Attack surface map (entrypoints, trust boundaries, sinks)
  - Top 5 exploit stories with realistic, step-by-step flow
  - Blast radius map from entrypoint to persistence
- Focus areas:
  - Auth/session boundaries
  - Input handling hotspots
  - Secrets and config risks
  - Dangerous sinks: shell/file/network/deserialization
  - Dependency smell spotting

## Agent 2 - Blue Team (Defender)
- Primary task: produce hardening actions and guardrails.
- Deliverables:
  - Patch suggestions + pseudo-diffs or PR-ready snippets
  - Mitigation plan ranked by ROI:
    - Quick wins
    - Structural hardening
    - Monitoring and alert hooks
  - Security tests and CI/pre-commit checks
- Focus areas:
    - auth gates
    - input contracts
    - auditability
    - failure visibility

## Agent 3 - Refactorer (Surgeon)
- Primary task: reduce future risk and maintenance drag.
- Deliverables:
  - Refactor roadmap (3 phases)
  - Minimal safe split of coupling hotspots
  - Test-first recommendations before code movement
- Focus areas:
  - Hotspot clusters (high complexity/coupling)
  - God modules
  - Dependency tangles
  - Test deserts

## Agent 4 - Historian (Time Traveler)
- Primary task: infer development history and predict drift.
- Deliverables:
  - Evolution narrative
  - Decay forecast (2 years)
  - Hiring/onboarding pain points
- Focus areas:
  - Conventions drift
  - Code churn signals
  - Change coupling among files
  - Single-owner critical modules

## Simulation report expectation
- For every iteration:
  - Red report
  - Blue report
  - Refactorer report
  - Historian report
- Final run report should include markdown sections for each team and a timeline:
  - what was attacked
  - what was defended/mitigated
  - what was refactored
  - whether the change reduced blast radius
