"""Rolling statistics per sensor: mean, std, z-score, EWMA, and rate of change, computed
on active_power. The EWMA's deviation from the rolling mean serves as the change-point
signal. Catches sudden jumps; expected to miss slow, gradual manipulation, which
motivates the ML and physics layers.
"""

import numpy as np

from config import settings
from detection.sensor_history import DetectionContext

FIELD = "active_power"


def evaluate(ctx: DetectionContext) -> tuple[float, dict]:
    values = [getattr(e, FIELD) for e in ctx.series]
    if len(values) < 5:
        return 0.0, {"reason": "insufficient_history"}

    history, current = values[:-1], values[-1]
    mean = float(np.mean(history))
    std = float(np.std(history))
    z_score = (current - mean) / std if std > 0 else 0.0

    ewma = history[0]
    for v in history[1:]:
        ewma = settings.EWMA_ALPHA * v + (1 - settings.EWMA_ALPHA) * ewma
    ewma_deviation = abs(current - ewma) / std if std > 0 else 0.0

    rate_of_change = current - history[-1]

    strongest = max(abs(z_score), ewma_deviation) / settings.Z_SCORE_THRESHOLD
    score = min(strongest, 1.0)
    evidence = {
        "z_score": round(z_score, 3),
        "ewma_deviation": round(ewma_deviation, 3),
        "rate_of_change": round(rate_of_change, 3),
    }
    return score, evidence
