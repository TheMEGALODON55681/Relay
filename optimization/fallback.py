"""Estimation fallback for a quarantined sensor stream: the median of its own recent
history. The gateway only ever records a reading while the sensor is TRUSTED (see
TrustedDataGateway.record), so this history is "last known good" by construction -
no poisoned reading ever enters it. Deliberately a plain statistic, not a solver.
"""

import statistics

from schemas.models import TelemetryEvent

HISTORY_WINDOW = 10


def estimate(history: list[TelemetryEvent]) -> float | None:
    if not history:
        return None
    return statistics.median(e.load for e in history)
