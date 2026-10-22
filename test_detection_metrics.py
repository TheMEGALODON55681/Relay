"""Tests for per-scenario detector performance aggregation."""
from evaluation.detection_metrics import aggregate_scenario_metrics


def test_metrics_are_grouped_per_attack_scenario_and_exclude_baseline():
    runs = [
        {"scenario": "BASELINE", "attack_detected": False,
         "detection_latency_ticks": None, "containment_latency_ticks": None},
        {"scenario": "LOAD_INFLATION", "attack_detected": True,
         "detection_latency_ticks": 2, "containment_latency_ticks": 4},
        {"scenario": "LOAD_INFLATION", "attack_detected": False,
         "detection_latency_ticks": None, "containment_latency_ticks": None},
        {"scenario": "COORDINATED_FDI", "attack_detected": True,
         "detection_latency_ticks": 1, "containment_latency_ticks": 2},
    ]

    result = aggregate_scenario_metrics(runs)

    assert "BASELINE" not in result
    assert result["LOAD_INFLATION"]["runs"] == 2
    assert result["LOAD_INFLATION"]["detected_runs"] == 1
    assert result["LOAD_INFLATION"]["undetected_runs"] == 1
    assert result["LOAD_INFLATION"]["detection_rate"] == 0.5
    assert result["LOAD_INFLATION"]["detection_latency_ticks"]["mean"] == 2.0
    assert result["LOAD_INFLATION"]["containment_latency_ticks"]["mean"] == 4.0
    assert result["COORDINATED_FDI"]["detection_rate"] == 1.0


def test_percentiles_are_reported_for_latency_samples():
    runs = [
        {"scenario": "A", "attack_detected": True,
         "detection_latency_ticks": latency, "containment_latency_ticks": latency + 1}
        for latency in range(1, 21)
    ]

    result = aggregate_scenario_metrics(runs)["A"]

    assert result["detection_latency_ticks"]["mean"] == 10.5
    assert result["detection_latency_ticks"]["median"] == 10.5
    assert result["detection_latency_ticks"]["p95"] == 19.05


def test_empty_and_missing_latency_inputs_are_safe():
    assert aggregate_scenario_metrics([]) == {}

    result = aggregate_scenario_metrics([
        {"scenario": "A", "attack_detected": False,
         "detection_latency_ticks": None, "containment_latency_ticks": None}
    ])

    assert result["A"]["detection_rate"] == 0.0
    assert result["A"]["undetected_runs"] == 1
    assert result["A"]["detection_latency_ticks"] == {
        "mean": None, "median": None, "p95": None
    }
    assert result["A"]["containment_latency_ticks"] == {
        "mean": None, "median": None, "p95": None
    }
