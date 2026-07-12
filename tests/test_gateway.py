"""Trusted data gateway: sensor labeling and the estimate/withhold contract that keeps
a quarantined sensor's raw reading away from the optimizer.
"""

from gateway.trusted_data_gateway import TrustedDataGateway
from tests.conftest import make_event


def test_default_status_is_trusted_and_raw_value_passes_through():
    gateway = TrustedDataGateway()
    event = make_event(load=50.0)
    assert gateway.status(event.sensor_id) == "TRUSTED"
    assert gateway.resolve_load(event) == 50.0


def test_quarantined_sensor_withholds_raw_value():
    gateway = TrustedDataGateway()
    event = make_event(load=90.0)
    gateway.record(event)
    gateway.quarantine(event.sensor_id)
    assert gateway.status(event.sensor_id) == "QUARANTINED"
    assert gateway.resolve_load(event) is None


def test_estimated_sensor_never_returns_the_poisoned_value():
    gateway = TrustedDataGateway()
    baseline = [make_event(tick=t, load=50.0) for t in range(5)]
    for event in baseline:
        gateway.record(event)
    # The poisoned reading itself is never recorded - record() is only ever called after
    # the detection/containment decision for an event, by which point a poisoned sensor
    # is no longer TRUSTED (see test_record_does_not_learn_from_a_reading_once_untrusted).
    poisoned = make_event(tick=5, load=90.0)
    gateway.enable_estimation(poisoned.sensor_id)

    resolved = gateway.resolve_load(poisoned)
    assert resolved is not None
    assert resolved != poisoned.load
    assert abs(resolved - 50.0) < 1.0


def test_quarantine_after_estimation_does_not_undo_it():
    """Containment playbooks fire quarantine, enable_estimation, and freeze together in
    that order (config/settings.py AUTONOMY_TIERS). freeze reuses the quarantine handler,
    so a later quarantine-type call must not strip away the estimate the previous one enabled.
    """
    gateway = TrustedDataGateway()
    event = make_event(load=90.0)
    gateway.record(event)
    gateway.quarantine(event.sensor_id)
    gateway.enable_estimation(event.sensor_id)
    gateway.quarantine(event.sensor_id)  # e.g. freeze_optimization_input, applied after
    assert gateway.status(event.sensor_id) == "ESTIMATED"
    assert gateway.resolve_load(event) is not None


def test_estimate_with_no_prior_trusted_history_withholds_rather_than_guessing():
    gateway = TrustedDataGateway()
    only_reading = make_event(load=90.0)
    # The very first reading for this sensor is itself the poisoned one - never recorded
    # while TRUSTED, so there's nothing safe to estimate from.
    gateway.enable_estimation(only_reading.sensor_id)
    assert gateway.resolve_load(only_reading) is None


def test_record_does_not_learn_from_a_reading_once_untrusted():
    """A sustained attack may produce several poisoned ticks before containment reacts.
    record() must not let any of those into history, even the ones recorded after
    quarantine but before an estimate is available.
    """
    gateway = TrustedDataGateway()
    baseline = make_event(tick=0, load=50.0)
    gateway.record(baseline)
    gateway.quarantine(baseline.sensor_id)

    still_poisoned = make_event(tick=1, load=200.0)
    gateway.record(still_poisoned)  # must be dropped: sensor is QUARANTINED, not TRUSTED

    gateway.enable_estimation(baseline.sensor_id)
    assert gateway.resolve_load(still_poisoned) == 50.0
