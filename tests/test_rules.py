"""Each rule category triggers on a crafted input that violates only that check."""

from detection import rule_engine
from simulator.grid import BATTERY, FEEDERS, SUBSTATION
from tests.conftest import make_context, make_event


def test_voltage_deviation_triggers():
    ctx = make_context(make_event(voltage=280.0))
    score, evidence = rule_engine.evaluate(ctx)
    assert "VOLTAGE_DEVIATION" in evidence
    assert score > 0


def test_frequency_anomaly_triggers():
    ctx = make_context(make_event(frequency=51.0))
    _, evidence = rule_engine.evaluate(ctx)
    assert "FREQUENCY_ANOMALY" in evidence


def test_load_spike_triggers():
    previous = make_event(load=10.0, active_power=10.0, tick=0)
    current = make_event(load=20.0, active_power=20.0, tick=1)
    ctx = make_context(current, series=[previous, current])
    _, evidence = rule_engine.evaluate(ctx)
    assert "LOAD_SPIKE" in evidence


def test_generation_load_mismatch_triggers():
    event = make_event(sensor_id=SUBSTATION, load=50.0, generation=80.0)
    ctx = make_context(event)
    _, evidence = rule_engine.evaluate(ctx)
    assert "GENERATION_LOAD_MISMATCH" in evidence


def test_impossible_battery_transition_triggers():
    previous = make_event(sensor_id=BATTERY, battery_soc=50.0, tick=0)
    current = make_event(sensor_id=BATTERY, battery_soc=90.0, tick=1)
    ctx = make_context(current, series=[previous, current])
    _, evidence = rule_engine.evaluate(ctx)
    assert "IMPOSSIBLE_BATTERY_TRANSITION" in evidence


def test_sensor_replay_pattern_triggers():
    previous = make_event(tick=0)
    current = make_event(tick=1)  # identical fields except timestamp
    ctx = make_context(current, series=[previous, current])
    _, evidence = rule_engine.evaluate(ctx)
    assert "SENSOR_REPLAY_PATTERN" in evidence


def test_timestamp_anomaly_triggers():
    previous = make_event(tick=0)
    current = make_event(tick=100)  # gap far larger than one tick
    ctx = make_context(current, series=[previous, current])
    _, evidence = rule_engine.evaluate(ctx)
    assert "TIMESTAMP_ANOMALY" in evidence


def test_sensor_rate_anomaly_triggers():
    values = [12.5, 12.65, 12.35, 12.55, 12.45, 40.0]
    series = [make_event(active_power=v, tick=i) for i, v in enumerate(values)]
    ctx = make_context(series[-1], series=series)
    _, evidence = rule_engine.evaluate(ctx)
    assert "SENSOR_RATE_ANOMALY" in evidence


def test_cross_sensor_inconsistency_triggers():
    snapshot = {f: make_event(sensor_id=f, voltage=230.0) for f in FEEDERS}
    sub_event = make_event(sensor_id=SUBSTATION, voltage=280.0)
    snapshot[SUBSTATION] = sub_event
    ctx = make_context(sub_event, snapshot=snapshot)
    _, evidence = rule_engine.evaluate(ctx)
    assert "CROSS_SENSOR_INCONSISTENCY" in evidence


def test_normal_reading_triggers_nothing():
    ctx = make_context(make_event())
    score, evidence = rule_engine.evaluate(ctx)
    assert score == 0.0
    assert evidence == {}
