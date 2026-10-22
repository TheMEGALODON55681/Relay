# Relay detector metrics contribution

## Files

- `evaluation/detection_metrics.py`: per-attack-scenario detection and containment metrics.
- `tests/test_detection_metrics.py`: focused unit tests.

## What it measures

For each non-`BASELINE` scenario:
- number of runs, detected runs, and undetected runs
- detection rate (undetected attacks remain in the denominator)
- mean, median, and p95 detection latency
- mean, median, and p95 containment latency

Latency summaries use available latency values only. An undetected run is not
assigned a fabricated latency of zero; its miss is visible in `undetected_runs`
and the detection-rate denominator. Empty latency samples return `None`.

## Add it to the repository

Copy these files into the matching folders in your Relay checkout. Then wire
the helper into `evaluation/report.py`:

```python
from evaluation.detection_metrics import aggregate_scenario_metrics
```

In `write_outputs(...)`, after computing the existing `detection` dictionary,
add the scenario breakdown to `metrics.json` without removing existing keys:

```python
scenario_metrics = aggregate_scenario_metrics(runs)
payload = {
    "detection": detection,
    "impact_prevented": impact,
    "per_scenario": scenario_metrics,
}
(out_dir / "metrics.json").write_text(json.dumps(payload, indent=2))
```

In `_render_markdown(...)`, add a "Per-scenario detector performance" table
using `scenario_metrics`. For each scenario show runs, detected/undetected,
detection rate, detection latency mean/median/p95, and containment latency
mean/median/p95. Keep the existing aggregate and impact-prevented sections.

Because I could not run the upstream repository's test suite in this environment,
run `pytest -q` from the repository root after copying and integrating these
files. Check the output report and ensure existing JSON consumers continue to
work with the additional `per_scenario` key.
