# Scoring Models

Use normalized scores in [0,1]. Clamp each metric to this range before weighted sums.

## Hotspot Score

hotspot =
0.35 * complexity +
0.25 * coupling_out +
0.20 * dependency_fragility +
0.20 * ownership_risk

## Attack Surface Score

attack_surface =
0.30 * exposed_entrypoints +
0.25 * trust_boundary_crossings +
0.25 * dangerous_sink_density +
0.20 * secret_exposure_risk

## Failure Likelihood

failure_likelihood =
0.40 * hotspot +
0.25 * runtime_concentration +
0.20 * external_dependency_weight +
0.15 * test_desert_factor

## Decay Score (24 months)

decay_score =
0.30 * complexity +
0.25 * coupling_total +
0.20 * ownership_risk +
0.15 * test_desert +
0.10 * churn_proxy

Recommended bands:
- 0.00-0.29 low
- 0.30-0.54 medium
- 0.55-0.74 high
- 0.75-1.00 critical

## Confidence

Lower confidence when:
- source files are skipped
- dynamic dispatch or reflection obscures call edges
- generated code dominates module volume

Attach confidence per artifact and mention assumptions explicitly.
