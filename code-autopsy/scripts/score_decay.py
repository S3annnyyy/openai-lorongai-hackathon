#!/usr/bin/env python3
"""Compute decay score per module from metrics.json."""

import argparse
import json
from pathlib import Path


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def band(score: float) -> str:
    if score < 0.30:
      return "low"
    if score < 0.55:
      return "medium"
    if score < 0.75:
      return "high"
    return "critical"


def compute(module: dict) -> float:
    complexity = clamp(float(module.get("complexity", 0.0)))
    coupling_total = clamp(
      (float(module.get("coupling_in", 0.0)) + float(module.get("coupling_out", 0.0))) / 20.0
    )
    ownership_risk = clamp(float(module.get("ownership_risk", 0.0)))
    test_desert = 1.0 - clamp(float(module.get("test_coverage_proxy", 0.0)))
    churn_proxy = clamp(float(module.get("dependency_fragility", 0.0)))

    return clamp(
      0.30 * complexity
      + 0.25 * coupling_total
      + 0.20 * ownership_risk
      + 0.15 * test_desert
      + 0.10 * churn_proxy
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Score 24-month decay risk")
    parser.add_argument("--metrics", required=True, help="Path to metrics.json")
    parser.add_argument("--out", required=True, help="Path to decay_forecast.json")
    args = parser.parse_args()

    with Path(args.metrics).open("r", encoding="utf-8") as f:
      metrics = json.load(f)

    modules = metrics.get("module_metrics", [])
    forecasts = []

    for module in modules:
      score = compute(module)
      forecasts.append(
        {
          "module": module.get("module", "unknown"),
          "decay_score": round(score, 4),
          "drivers": ["complexity", "coupling", "ownership_risk", "test_desert"],
          "maintainability_risk": band(score),
        }
      )

    output = {"window_months": 24, "module_forecasts": forecasts}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
