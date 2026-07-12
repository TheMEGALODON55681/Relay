"""Aggregates a harness run's EvaluationRun list into results/metrics.csv,
metrics.json, and a rendered markdown table (PRD Section 9/12).
"""

import csv
import json
import statistics
from pathlib import Path

from evaluation import ab_compare
from schemas.models import EvaluationRun


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _aggregate_detection_metrics(runs: list[EvaluationRun], pre_onset_readings: int, pre_onset_triggers: int) -> dict:
    attack_runs = [r for r in runs if r.scenario != "BASELINE"]
    latencies = [r.detection_latency_ticks for r in attack_runs if r.detection_latency_ticks is not None]
    containments = [r.containment_latency_ticks for r in attack_runs if r.containment_latency_ticks is not None]
    return {
        "detection_rate": round(_mean(r.attack_detected for r in attack_runs), 4),
        "false_positive_rate": round(pre_onset_triggers / pre_onset_readings, 6) if pre_onset_readings else 0.0,
        "mean_detection_latency_ticks": round(statistics.mean(latencies), 2) if latencies else None,
        "mean_containment_latency_ticks": round(statistics.mean(containments), 2) if containments else None,
    }


def _write_csv(runs: list[EvaluationRun], path: Path) -> None:
    fields = list(EvaluationRun.model_fields)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            writer.writerow(run.model_dump())


def _render_markdown(detection: dict, impact: dict) -> str:
    lines = [
        "## Detection results",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Detection rate | {detection['detection_rate']:.1%} |",
        f"| False positive rate | {detection['false_positive_rate']:.3%} |",
        f"| Mean detection latency (ticks) | {detection['mean_detection_latency_ticks']} |",
        f"| Mean containment latency (ticks) | {detection['mean_containment_latency_ticks']} |",
        "",
        "## Security ON vs OFF: impact prevented (summed across runs)",
        "",
        "| Scenario | Cost prevented | Emissions prevented | Unnecessary generation prevented (MWh) |",
        "|---|---|---|---|",
    ]
    for scenario, entry in impact.items():
        lines.append(f"| {scenario} | {entry['dispatch_cost_prevented']} | {entry['dispatch_emissions_prevented']} | {entry['unnecessary_generation_mwh_prevented']} |")
    lines += [
        "",
        "Unnecessary generation (MWh) is the deviation from the true load and is the",
        "reliable cross-scenario signal. Dollar cost prevented can be negative for",
        "LOAD_SUPPRESSION: without security the optimizer under-generates against a",
        "falsely low reading, which is cheaper but unsafe (insufficient reserve); with",
        "security dispatch is restored to the true, higher load, which costs more but",
        "removes the deviation from truth. That is security working as intended, not a",
        "regression - see PROJECT_PLAN.md Section 6.",
        "",
        "COORDINATED_FDI shifts feeder sensors, not the substation the optimizer dispatches",
        "from, so its own reading stays correct in most runs and ON/OFF dispatch is",
        "identical. In a minority of runs the substation's cross-sensor physics evidence",
        "still implicates it, containment quarantines it as a precaution, and the gateway's",
        "estimate introduces a small deviation from its own already-correct live reading -",
        "the near-zero or slightly negative numbers above are that estimation noise, not a",
        "detection failure: the underlying attack is still caught (see detection rate).",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(runs: list[EvaluationRun], out_dir: Path, pre_onset_readings: int, pre_onset_triggers: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(runs, out_dir / "metrics.csv")

    detection = _aggregate_detection_metrics(runs, pre_onset_readings, pre_onset_triggers)
    impact = ab_compare.compare(runs)
    (out_dir / "metrics.json").write_text(json.dumps({"detection": detection, "impact_prevented": impact}, indent=2))
    (out_dir / "metrics.md").write_text(_render_markdown(detection, impact))
