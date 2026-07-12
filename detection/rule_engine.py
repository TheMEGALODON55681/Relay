"""Deterministic threshold checks producing a normalized rule score per PRD Section 5.

Categories: VOLTAGE_DEVIATION, FREQUENCY_ANOMALY, LOAD_SPIKE, GENERATION_LOAD_MISMATCH,
IMPOSSIBLE_BATTERY_TRANSITION, SENSOR_REPLAY_PATTERN, TIMESTAMP_ANOMALY, SENSOR_RATE_ANOMALY,
CROSS_SENSOR_INCONSISTENCY.
"""

import numpy as np

from config import settings
from detection.sensor_history import DetectionContext
from simulator.grid import BATTERY, FEEDERS, SUBSTATION

RuleHit = tuple[str, float, dict]


def _voltage_deviation(ctx: DetectionContext) -> RuleHit | None:
    e = ctx.event
    deviation = abs(e.voltage - settings.VOLTAGE_NOMINAL) / settings.VOLTAGE_NOMINAL
    if deviation <= settings.VOLTAGE_DEVIATION_PCT:
        return None
    severity = min(deviation / settings.VOLTAGE_DEVIATION_PCT, 3.0) / 3.0
    return "VOLTAGE_DEVIATION", severity, {"voltage": e.voltage, "deviation_pct": round(deviation, 4)}


def _frequency_anomaly(ctx: DetectionContext) -> RuleHit | None:
    e = ctx.event
    deviation = abs(e.frequency - settings.FREQUENCY_NOMINAL)
    if deviation <= settings.FREQUENCY_DEVIATION_HZ:
        return None
    severity = min(deviation / settings.FREQUENCY_DEVIATION_HZ, 3.0) / 3.0
    return "FREQUENCY_ANOMALY", severity, {"frequency": e.frequency, "deviation_hz": round(deviation, 4)}


def _load_spike(ctx: DetectionContext) -> RuleHit | None:
    e, prev = ctx.event, ctx.previous
    if prev is None or prev.load <= 0:
        return None
    change = (e.load - prev.load) / prev.load
    if change <= settings.LOAD_SPIKE_PCT:
        return None
    severity = min(change / settings.LOAD_SPIKE_PCT, 3.0) / 3.0
    return "LOAD_SPIKE", severity, {"previous_load": prev.load, "current_load": e.load, "change_pct": round(change, 4)}


def _generation_load_mismatch(ctx: DetectionContext) -> RuleHit | None:
    e = ctx.event
    if e.asset_id != SUBSTATION or e.load <= 0:
        return None
    mismatch = abs(e.generation - e.load) / e.load
    if mismatch <= settings.GENERATION_LOAD_MISMATCH_PCT:
        return None
    severity = min(mismatch / settings.GENERATION_LOAD_MISMATCH_PCT, 3.0) / 3.0
    return "GENERATION_LOAD_MISMATCH", severity, {
        "generation": e.generation,
        "load": e.load,
        "mismatch_pct": round(mismatch, 4),
    }


def _impossible_battery_transition(ctx: DetectionContext) -> RuleHit | None:
    e, prev = ctx.event, ctx.previous
    if e.asset_id != BATTERY or prev is None:
        return None
    step = abs(e.battery_soc - prev.battery_soc) / 100.0
    if step <= settings.BATTERY_SOC_MAX_STEP_PCT:
        return None
    severity = min(step / settings.BATTERY_SOC_MAX_STEP_PCT, 3.0) / 3.0
    return "IMPOSSIBLE_BATTERY_TRANSITION", severity, {
        "previous_soc": prev.battery_soc,
        "current_soc": e.battery_soc,
    }


def _sensor_replay_pattern(ctx: DetectionContext) -> RuleHit | None:
    e, prev = ctx.event, ctx.previous
    if prev is None:
        return None
    fields = (e.voltage, e.current, e.frequency, e.active_power)
    prev_fields = (prev.voltage, prev.current, prev.frequency, prev.active_power)
    if fields != prev_fields:
        return None
    return "SENSOR_REPLAY_PATTERN", 0.8, {"repeated_active_power": e.active_power}


def _timestamp_anomaly(ctx: DetectionContext) -> RuleHit | None:
    e, prev = ctx.event, ctx.previous
    if prev is None:
        return None
    gap = (e.timestamp - prev.timestamp).total_seconds()
    deviation = abs(gap - settings.TICK_SECONDS)
    if gap > 0 and deviation <= settings.TIMESTAMP_ANOMALY_SECONDS:
        return None
    severity = 1.0 if gap <= 0 else min(deviation / settings.TIMESTAMP_ANOMALY_SECONDS, 3.0) / 3.0
    return "TIMESTAMP_ANOMALY", severity, {"gap_seconds": round(gap, 3)}


def _sensor_rate_anomaly(ctx: DetectionContext) -> RuleHit | None:
    series = ctx.series
    if len(series) < 5:
        return None
    deltas = [series[i].active_power - series[i - 1].active_power for i in range(1, len(series))]
    history, current = deltas[:-1], deltas[-1]
    std = float(np.std(history)) if history else 0.0
    if std == 0:
        return None
    multiple = abs(current) / std
    if multiple <= settings.SENSOR_RATE_MAX_STD_MULTIPLE:
        return None
    severity = min(multiple / settings.SENSOR_RATE_MAX_STD_MULTIPLE, 3.0) / 3.0
    return "SENSOR_RATE_ANOMALY", severity, {"delta": round(current, 3), "std_multiple": round(multiple, 2)}


def _cross_sensor_inconsistency(ctx: DetectionContext) -> RuleHit | None:
    """Substation voltage should roughly track its feeders'. Load aggregation is the
    physics validator's job (physics_validator.py); this is the coarser, faster signal.
    """
    e = ctx.event
    if e.asset_id != SUBSTATION:
        return None
    feeders = [ctx.snapshot[f] for f in FEEDERS if f in ctx.snapshot]
    if len(feeders) < len(FEEDERS):
        return None
    feeder_voltage_avg = sum(r.voltage for r in feeders) / len(feeders)
    deviation = abs(e.voltage - feeder_voltage_avg) / feeder_voltage_avg
    if deviation <= settings.VOLTAGE_DEVIATION_PCT:
        return None
    severity = min(deviation / settings.VOLTAGE_DEVIATION_PCT, 3.0) / 3.0
    return "CROSS_SENSOR_INCONSISTENCY", severity, {
        "substation_voltage": e.voltage,
        "feeder_voltage_avg": round(feeder_voltage_avg, 2),
        "deviation_pct": round(deviation, 4),
    }


_CHECKS = [
    _voltage_deviation,
    _frequency_anomaly,
    _load_spike,
    _generation_load_mismatch,
    _impossible_battery_transition,
    _sensor_replay_pattern,
    _timestamp_anomaly,
    _sensor_rate_anomaly,
    _cross_sensor_inconsistency,
]


def evaluate(ctx: DetectionContext) -> tuple[float, dict]:
    """Returns (rule_score in 0..1, evidence dict of triggered rule -> detail)."""
    evidence: dict[str, dict] = {}
    severities: list[float] = []
    for check in _CHECKS:
        hit = check(ctx)
        if hit:
            name, severity, detail = hit
            evidence[name] = detail
            severities.append(severity)
    rule_score = min(sum(severities), 1.0) if severities else 0.0
    return rule_score, evidence
