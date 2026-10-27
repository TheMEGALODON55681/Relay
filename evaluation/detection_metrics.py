"""Per-scenario detector performance metrics for Relay evaluation runs.

This module is intentionally independent of the report renderer so it can be
unit-tested without running the full simulation harness.

Metrics are computed from EvaluationRun-like objects (or dictionaries) with
these fields:
    scenario, attack_detected, detection_latency_ticks,
    containment_latency_ticks

Undetected attacks are included in the detection-rate denominator, but have no
detection latency. Latency summaries are therefore calculated over detected
runs only; the undetected count is reported separately to avoid hiding misses.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def _get(run: Any, field: str, default: Any = None) -> Any:
    """Read a field from either a Pydantic model or a mapping."""
    if isinstance(run, Mapping):
        return run.get(field, default)
    return getattr(run, field, default)


def _percentile(values: list[float], percentile: float) -> float | None:
    """Return a linearly interpolated percentile, or None for no observations."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    result = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return round(result, 2)


def _latency_summary(values: list[int | float]) -> dict[str, float | None]:
    numeric = [float(value) for value in values if value is not None]
    return {
        "mean": round(statistics.mean(numeric), 2) if numeric else None,
        "median": _percentile(numeric, 0.50),
        "p95": _percentile(numeric, 0.95),
    }


def aggregate_scenario_metrics(runs: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Aggregate detector and containment metrics for each attack scenario.

    BASELINE runs are excluded because they are not attack trials. Runs with
    missing detection latency are not silently treated as zero-latency runs.
    """
    grouped: dict[str, list[Any]] = defaultdict(list)
    for run in runs:
        scenario = _get(run, "scenario")
        if not scenario or scenario == "BASELINE":
            continue
        grouped[str(scenario)].append(run)

    results: dict[str, dict[str, Any]] = {}
    for scenario in sorted(grouped):
        scenario_runs = grouped[scenario]
        total = len(scenario_runs)
        detected_runs = [
            run for run in scenario_runs if bool(_get(run, "attack_detected", False))
        ]
        detection_latencies = [
            _get(run, "detection_latency_ticks")
            for run in detected_runs
            if _get(run, "detection_latency_ticks") is not None
        ]
        containment_latencies = [
            _get(run, "containment_latency_ticks")
            for run in scenario_runs
            if _get(run, "containment_latency_ticks") is not None
        ]

        results[scenario] = {
            "runs": total,
            "detected_runs": len(detected_runs),
            "undetected_runs": total - len(detected_runs),
            "detection_rate": round(len(detected_runs) / total, 4) if total else 0.0,
            "detection_latency_ticks": _latency_summary(detection_latencies),
            "containment_latency_ticks": _latency_summary(containment_latencies),
        }
    return results
