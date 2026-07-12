"""Physics validator: each check passes on balanced input and flags unbalanced input."""

from config import settings
from detection import physics_validator
from simulator.grid import BATTERY, FEEDERS, GENERATORS, SUBSTATION
from tests.conftest import make_context, make_event


def _balanced_snapshot(battery_flow: float = 0.0) -> dict:
    feeder_loads = {f: 12.5 for f in FEEDERS}
    load_total = sum(feeder_loads.values())
    gen_total = load_total * (1 + settings.ESTIMATED_LOSS_PCT) - battery_flow
    gen_each = gen_total / len(GENERATORS)

    snapshot = {g: make_event(sensor_id=g, active_power=gen_each, load=0.0, generation=gen_each) for g in GENERATORS}
    snapshot |= {f: make_event(sensor_id=f, active_power=load, load=load, generation=0.0) for f, load in feeder_loads.items()}
    snapshot[SUBSTATION] = make_event(sensor_id=SUBSTATION, active_power=gen_total, load=load_total, generation=gen_total)
    snapshot[BATTERY] = make_event(sensor_id=BATTERY, active_power=battery_flow, load=0.0, generation=0.0)
    return snapshot


def test_power_balance_passes_when_balanced():
    snapshot = _balanced_snapshot()
    ctx = make_context(snapshot[BATTERY], snapshot=snapshot)
    score, evidence = physics_validator.evaluate(ctx)
    assert score == 0.0
    assert evidence == {}


def test_power_balance_flags_imbalance():
    snapshot = _balanced_snapshot()
    snapshot[FEEDERS[0]] = make_event(sensor_id=FEEDERS[0], active_power=40.0, load=40.0, generation=0.0)
    ctx = make_context(snapshot[BATTERY], snapshot=snapshot)
    score, evidence = physics_validator.evaluate(ctx)
    assert score > 0.0
    assert "POWER_BALANCE" in evidence


def test_substation_aggregation_passes_when_balanced():
    snapshot = _balanced_snapshot()
    ctx = make_context(snapshot[SUBSTATION], snapshot=snapshot)
    score, _ = physics_validator.evaluate(ctx)
    assert score == 0.0


def test_substation_aggregation_flags_mismatch():
    snapshot = _balanced_snapshot()
    load_total = sum(snapshot[f].load for f in FEEDERS)
    inflated = load_total * 1.5
    snapshot[SUBSTATION] = make_event(sensor_id=SUBSTATION, active_power=inflated, load=inflated, generation=inflated)
    ctx = make_context(snapshot[SUBSTATION], snapshot=snapshot)
    score, evidence = physics_validator.evaluate(ctx)
    assert score > 0.0
    assert "SUBSTATION_AGGREGATION" in evidence


def test_battery_soc_continuity_passes_when_consistent():
    previous = make_event(sensor_id=BATTERY, battery_soc=50.0, active_power=1.0, tick=0)
    expected_delta = -1.0 * settings.BATTERY_SOC_SENSITIVITY_PCT_PER_MW
    current = make_event(sensor_id=BATTERY, battery_soc=50.0 + expected_delta, active_power=1.0, tick=1)
    ctx = make_context(current, series=[previous, current])
    score, _ = physics_validator.evaluate(ctx)
    assert score == 0.0


def test_battery_soc_continuity_flags_discrepancy():
    previous = make_event(sensor_id=BATTERY, battery_soc=50.0, active_power=1.0, tick=0)
    current = make_event(sensor_id=BATTERY, battery_soc=70.0, active_power=1.0, tick=1)
    ctx = make_context(current, series=[previous, current])
    score, evidence = physics_validator.evaluate(ctx)
    assert score > 0.0
    assert "BATTERY_SOC_CONTINUITY" in evidence
