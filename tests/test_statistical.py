"""Statistical detector: rolling stats and the EWMA-deviation change-point signal."""

import numpy as np

from detection import statistical_detector
from tests.conftest import make_context, make_event


def test_insufficient_history_returns_zero():
    ctx = make_context(make_event(), series=[make_event()])
    score, evidence = statistical_detector.evaluate(ctx)
    assert score == 0.0
    assert evidence == {"reason": "insufficient_history"}


def test_constant_history_gives_zero_z_score():
    series = [make_event(active_power=10.0, tick=i) for i in range(5)]
    ctx = make_context(series[-1], series=series)
    _, evidence = statistical_detector.evaluate(ctx)
    assert evidence["z_score"] == 0.0
    assert evidence["ewma_deviation"] == 0.0


def test_large_deviation_flags_high_z_score():
    rng = np.random.default_rng(1)
    history = [make_event(active_power=12.5 + rng.normal(0, 0.2), tick=i) for i in range(20)]
    spike = make_event(active_power=30.0, tick=20)
    ctx = make_context(spike, series=history + [spike])
    score, evidence = statistical_detector.evaluate(ctx)
    assert score == 1.0
    assert abs(evidence["z_score"]) > 3.0


def test_level_shift_flags_ewma_deviation():
    rng = np.random.default_rng(2)
    stable = [make_event(active_power=12.5 + rng.normal(0, 0.1), tick=i) for i in range(10)]
    shifted = make_event(active_power=20.0, tick=10)
    ctx = make_context(shifted, series=stable + [shifted])
    score, _ = statistical_detector.evaluate(ctx)
    assert score > 0.0
