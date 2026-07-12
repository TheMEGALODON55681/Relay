"""Isolation Forest anomaly detector. Trained once on normal-only simulated telemetry
and persisted to disk; loaded lazily (and trained on first use if the file is missing)
at evaluation time.
"""

from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from config import settings
from detection.sensor_history import DetectionContext, SensorHistory
from schemas.models import TelemetryEvent
from simulator.grid import FEEDERS, GENERATORS, SENSOR_KIND, Grid
from simulator.telemetry import emit_tick

_cache: dict = {}


def _features(ctx: DetectionContext) -> np.ndarray:
    e = ctx.event
    values = [s.active_power for s in ctx.series]
    history = values[:-1] if len(values) > 1 else values
    rolling_mean = float(np.mean(history))
    rolling_std = float(np.std(history)) if len(history) > 1 else 0.0
    rate_of_change = values[-1] - values[-2] if len(values) >= 2 else 0.0

    peers = [
        r
        for sid, r in ctx.snapshot.items()
        if sid != e.sensor_id and SENSOR_KIND.get(sid) == SENSOR_KIND.get(e.sensor_id)
    ]
    sensor_difference = e.active_power - (sum(p.active_power for p in peers) / len(peers)) if peers else 0.0

    gen_total = sum(ctx.snapshot[g].generation for g in GENERATORS if g in ctx.snapshot)
    load_total = sum(ctx.snapshot[f].load for f in FEEDERS if f in ctx.snapshot)
    upstream_downstream_difference = gen_total - load_total

    return np.array(
        [
            e.voltage, e.current, e.frequency, e.active_power, e.reactive_power,
            e.power_factor, e.load, e.generation, e.battery_soc,
            rate_of_change, rolling_mean, rolling_std,
            e.timestamp.hour, e.timestamp.weekday(),
            sensor_difference, upstream_downstream_difference,
        ]
    )


def _simulate_normal_features(n_samples: int) -> np.ndarray:
    grid = Grid()
    history = SensorHistory()
    rows = []
    while len(rows) < n_samples:
        for reading in emit_tick(grid):
            ctx = history.push(TelemetryEvent(**reading))
            rows.append(_features(ctx))
    return np.array(rows[:n_samples])


def train_and_persist(n_samples: int = settings.IFOREST_TRAIN_SAMPLES) -> None:
    features = _simulate_normal_features(n_samples)
    clf = IsolationForest(
        n_estimators=settings.IFOREST_N_ESTIMATORS,
        contamination=settings.IFOREST_CONTAMINATION,
        random_state=settings.RANDOM_SEED,
    )
    clf.fit(features)
    scores = clf.decision_function(features)
    Path(settings.ML_MODEL_PATH).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": clf, "score_min": float(scores.min()), "score_max": float(scores.max())},
        settings.ML_MODEL_PATH,
    )


def _load_bundle() -> dict:
    if "bundle" not in _cache:
        if not Path(settings.ML_MODEL_PATH).exists():
            train_and_persist()
        _cache["bundle"] = joblib.load(settings.ML_MODEL_PATH)
    return _cache["bundle"]


def evaluate(ctx: DetectionContext) -> tuple[float, dict]:
    if len(ctx.series) < 2:
        return 0.0, {"reason": "insufficient_history"}
    bundle = _load_bundle()
    clf, score_min, score_max = bundle["model"], bundle["score_min"], bundle["score_max"]
    raw_score = float(clf.decision_function(_features(ctx).reshape(1, -1))[0])
    span = score_max - score_min
    ml_score = float(np.clip((score_max - raw_score) / span, 0.0, 1.0)) if span > 0 else 0.5
    return ml_score, {"raw_score": round(raw_score, 4)}
