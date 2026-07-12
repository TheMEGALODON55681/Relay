"""Security ON versus OFF comparison: for each attack scenario, aggregates the paired
runs and reports the cost, emissions, and unnecessary-generation impact security
prevented. This is the project's headline result (PROJECT_PLAN.md Section 2).
"""

from schemas.models import EvaluationRun

_METRICS = ("dispatch_cost", "dispatch_emissions", "unnecessary_generation_mwh")


def compare(runs: list[EvaluationRun]) -> dict[str, dict[str, float]]:
    """One entry per attack scenario (BASELINE excluded - there's no attack to prevent
    the impact of). Each metric is summed across runs, per PRD Section 9's "impact
    prevented... summed across attack runs," with off/on totals and the delta (off - on:
    what having security enabled avoided).
    """
    result = {}
    for scenario in sorted({r.scenario for r in runs if r.scenario != "BASELINE"}):
        on = [r for r in runs if r.scenario == scenario and r.security_enabled]
        off = [r for r in runs if r.scenario == scenario and not r.security_enabled]
        result[scenario] = _delta(on, off)
    return result


def _delta(on: list[EvaluationRun], off: list[EvaluationRun]) -> dict[str, float]:
    entry = {}
    for metric in _METRICS:
        on_total = sum(getattr(r, metric) for r in on)
        off_total = sum(getattr(r, metric) for r in off)
        entry[f"{metric}_on"] = round(on_total, 4)
        entry[f"{metric}_off"] = round(off_total, 4)
        entry[f"{metric}_prevented"] = round(off_total - on_total, 4)
    return entry
