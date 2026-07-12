"""Three physics consistency checks, each a violation magnitude normalized to 0..1;
the physics score is the strongest violation. This layer is what exposes coordinated
stealth FDI, where individual readings look plausible but the physical relationships
do not balance.
"""

from config import settings
from detection.sensor_history import DetectionContext
from simulator.grid import BATTERY, FEEDERS, GENERATORS, SUBSTATION

PhysicsHit = tuple[float, dict]


def _power_balance(ctx: DetectionContext) -> PhysicsHit | None:
    # Only evaluated on the battery event: it is last in each tick's reporting order
    # (see simulator/grid.py), so it is the one moment every peer is guaranteed fresh
    # for the same tick rather than a stale carry-over from the previous one.
    if ctx.event.asset_id != BATTERY:
        return None
    snap = ctx.snapshot
    if not all(s in snap for s in (*GENERATORS, *FEEDERS, BATTERY)):
        return None
    load_total = sum(snap[f].load for f in FEEDERS)
    if load_total <= 0:
        return None
    gen_total = sum(snap[g].generation for g in GENERATORS)
    battery_flow = snap[BATTERY].active_power
    battery_discharge, battery_charge = max(battery_flow, 0.0), max(-battery_flow, 0.0)
    estimated_loss = settings.ESTIMATED_LOSS_PCT * load_total
    residual = gen_total + battery_discharge - load_total - battery_charge - estimated_loss
    residual_pct = abs(residual) / load_total
    if residual_pct <= settings.POWER_BALANCE_TOLERANCE:
        return None
    violation = min(residual_pct / settings.POWER_BALANCE_TOLERANCE, 3.0) / 3.0
    return violation, {"residual": round(residual, 3), "residual_pct": round(residual_pct, 4)}


def _substation_aggregation(ctx: DetectionContext) -> PhysicsHit | None:
    e = ctx.event
    if e.asset_id != SUBSTATION:
        return None
    feeders = [ctx.snapshot[f] for f in FEEDERS if f in ctx.snapshot]
    if len(feeders) < len(FEEDERS):
        return None
    feeder_total = sum(r.load for r in feeders)
    if feeder_total <= 0:
        return None
    mismatch = abs(e.load - feeder_total) / feeder_total
    if mismatch <= settings.AGGREGATION_TOLERANCE:
        return None
    violation = min(mismatch / settings.AGGREGATION_TOLERANCE, 3.0) / 3.0
    return violation, {
        "substation_load": e.load,
        "feeder_total": round(feeder_total, 3),
        "mismatch_pct": round(mismatch, 4),
    }


def _battery_soc_continuity(ctx: DetectionContext) -> PhysicsHit | None:
    e, prev = ctx.event, ctx.previous
    if e.asset_id != BATTERY or prev is None:
        return None
    expected_delta = -e.active_power * settings.BATTERY_SOC_SENSITIVITY_PCT_PER_MW
    actual_delta = e.battery_soc - prev.battery_soc
    discrepancy = abs(actual_delta - expected_delta) / 100.0
    if discrepancy <= settings.BATTERY_SOC_TOLERANCE:
        return None
    violation = min(discrepancy / settings.BATTERY_SOC_TOLERANCE, 3.0) / 3.0
    return violation, {"expected_delta": round(expected_delta, 3), "actual_delta": round(actual_delta, 3)}


_CHECKS = [
    ("POWER_BALANCE", _power_balance),
    ("SUBSTATION_AGGREGATION", _substation_aggregation),
    ("BATTERY_SOC_CONTINUITY", _battery_soc_continuity),
]


def evaluate(ctx: DetectionContext) -> tuple[float, dict]:
    """Returns (physics_score in 0..1, evidence dict of triggered check -> detail)."""
    evidence: dict[str, dict] = {}
    violations = [0.0]
    for name, check in _CHECKS:
        hit = check(ctx)
        if hit:
            violation, detail = hit
            evidence[name] = detail
            violations.append(violation)
    return max(violations), evidence
