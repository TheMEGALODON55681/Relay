"""Trusted data gateway: sensor labeling and the constraint-reconstruction contract
that keeps a quarantined sensor's raw reading away from the optimizer. See
gateway.trusted_data_gateway's module docstring for the observability rule this
verifies: reconstructable iff sensor_id is the single unknown in a constraint where
every other member is TRUSTED.
"""

from gateway.trusted_data_gateway import TrustedDataGateway
from schemas.models import ResponseAction
from simulator.grid import FEEDERS, SUBSTATION
from soc.tools import response_tools
from tests.conftest import make_event


def _trust_feeders(gateway: TrustedDataGateway, loads: dict[str, float], tick: int = 0) -> None:
    for sensor_id, load in loads.items():
        gateway.record(make_event(sensor_id=sensor_id, tick=tick, load=load))


def test_default_status_is_trusted_and_raw_value_passes_through():
    gateway = TrustedDataGateway()
    event = make_event(load=50.0)
    assert gateway.status(event.sensor_id) == "TRUSTED"
    assert gateway.resolve_load(event) == 50.0


def test_quarantined_sensor_returns_none_not_stale_value():
    gateway = TrustedDataGateway()
    event = make_event(load=90.0)
    gateway.record(event)
    gateway.quarantine(event.sensor_id)
    assert gateway.status(event.sensor_id) == "QUARANTINED"
    assert gateway.resolve_load(event) is None


def test_estimation_succeeds_with_sufficient_trusted_peers():
    """Single-sensor compromise: every other member of SUBSTATION_AGGREGATION is
    TRUSTED, so the substation is the sole unknown and reconstructs exactly.
    """
    gateway = TrustedDataGateway()
    _trust_feeders(gateway, {FEEDERS[0]: 12.5, FEEDERS[1]: 12.5, FEEDERS[2]: 12.5, FEEDERS[3]: 12.5})
    poisoned = make_event(sensor_id=SUBSTATION, load=90.0)

    gateway.quarantine(SUBSTATION)
    result = gateway.enable_estimation(SUBSTATION)

    assert result.success is True
    assert result.state == "ESTIMATED"
    assert result.estimate is not None
    assert abs(result.estimate - 50.0) < 1e-9
    assert result.confidence is not None
    assert gateway.status(SUBSTATION) == "ESTIMATED"

    resolved = gateway.resolve_load(poisoned)
    assert resolved is not None
    assert resolved != poisoned.load


def test_estimation_fails_when_group_is_unobservable():
    """Two feeders untrusted (never recorded) leaves the substation with two unknowns
    in its only constraint: underdetermined, so it stays QUARANTINED with nothing served.
    """
    gateway = TrustedDataGateway()
    _trust_feeders(gateway, {FEEDERS[0]: 12.5, FEEDERS[1]: 12.5})
    # FEEDER-3 and FEEDER-4 never recorded - not TRUSTED, so they count as unknowns too.

    gateway.quarantine(SUBSTATION)
    result = gateway.enable_estimation(SUBSTATION)

    assert result.success is False
    assert result.state == "QUARANTINED"
    assert result.estimate is None
    assert "unobservable" in result.reason
    assert gateway.status(SUBSTATION) == "QUARANTINED"
    assert gateway.resolve_load(make_event(sensor_id=SUBSTATION, load=90.0)) is None


def test_estimated_sensor_is_not_a_valid_estimation_source():
    """THE ONE RULE. FEEDER-1 becomes ESTIMATED first; a later attempt to reconstruct
    FEEDER-2 through the same constraint must not accept FEEDER-1's estimate as a known
    - only TRUSTED sources count, so FEEDER-2 is left with two unknowns and stays
    QUARANTINED even though FEEDER-1 has a number sitting right there.
    """
    gateway = TrustedDataGateway()
    _trust_feeders(gateway, {SUBSTATION: 100.0, FEEDERS[0]: 25.0, FEEDERS[1]: 25.0, FEEDERS[2]: 25.0, FEEDERS[3]: 25.0})

    gateway.quarantine(FEEDERS[0])
    first = gateway.enable_estimation(FEEDERS[0])
    assert first.success is True
    assert gateway.status(FEEDERS[0]) == "ESTIMATED"

    gateway.quarantine(FEEDERS[1])
    second = gateway.enable_estimation(FEEDERS[1])

    assert second.success is False
    assert second.state == "QUARANTINED"
    assert "2 unknowns" in second.reason


def test_quarantine_cascades_a_degrade_when_a_peer_becomes_untrusted():
    """Mirrors the ESCALATING_FDI demo: an ESTIMATED sensor degrades back to
    QUARANTINED, without a fresh enable_estimation call, the moment enough of its
    constraint's other members stop being TRUSTED.
    """
    gateway = TrustedDataGateway()
    _trust_feeders(gateway, {SUBSTATION: 100.0, FEEDERS[0]: 25.0, FEEDERS[1]: 25.0, FEEDERS[2]: 25.0, FEEDERS[3]: 25.0})
    gateway.quarantine(FEEDERS[0])
    gateway.enable_estimation(FEEDERS[0])
    assert gateway.status(FEEDERS[0]) == "ESTIMATED"

    gateway.quarantine(FEEDERS[1])
    gateway.quarantine(FEEDERS[2])
    gateway.quarantine(FEEDERS[3])

    assert gateway.status(FEEDERS[0]) == "QUARANTINED"
    assert gateway.resolve_load(make_event(sensor_id=FEEDERS[0], load=25.0)) is None


def test_quarantine_after_estimation_does_not_undo_it():
    """Containment playbooks fire quarantine, enable_estimation, and freeze together in
    that order (config/settings.py AUTONOMY_TIERS). freeze reuses the quarantine handler,
    so a later quarantine-type call on the SAME sensor must not strip away the estimate
    the previous one enabled.
    """
    gateway = TrustedDataGateway()
    _trust_feeders(gateway, {FEEDERS[0]: 12.5, FEEDERS[1]: 12.5, FEEDERS[2]: 12.5, FEEDERS[3]: 12.5})
    gateway.quarantine(SUBSTATION)
    gateway.enable_estimation(SUBSTATION)
    gateway.quarantine(SUBSTATION)  # e.g. freeze_optimization_input, applied after
    assert gateway.status(SUBSTATION) == "ESTIMATED"
    assert gateway.resolve_load(make_event(sensor_id=SUBSTATION, load=90.0)) is not None


def test_sensor_outside_any_constraint_stays_quarantined():
    """A generator or the battery participates in no constraint today - never
    reconstructable, so an estimation attempt is honest about withholding rather than
    inventing a number.
    """
    gateway = TrustedDataGateway()
    gateway.quarantine("GEN-1")
    result = gateway.enable_estimation("GEN-1")
    assert result.success is False
    assert result.state == "QUARANTINED"
    assert "not covered by any reconstruction constraint" in result.reason


def test_enable_estimation_is_a_noop_on_a_still_trusted_sensor():
    """A correlated re-proposal (soc/orchestrator.py's _propose_for_new_assets) can
    generate ENABLE_ESTIMATION_FALLBACK for an asset that was never quarantined. It
    must not silently promote a fine, TRUSTED sensor to ESTIMATED.
    """
    gateway = TrustedDataGateway()
    result = gateway.enable_estimation(SUBSTATION)
    assert result.success is True
    assert result.state == "TRUSTED"
    assert gateway.status(SUBSTATION) == "TRUSTED"


def test_execute_all_orders_quarantine_before_estimation_regardless_of_input_order():
    """Regression: a correlated re-proposal builds action types from a set (see
    soc/orchestrator.py), so ENABLE_ESTIMATION_FALLBACK can end up listed before
    QUARANTINE_SENSOR for the same target - and an LLM's own proposal order isn't
    guaranteed either. execute_all must not let the out-of-order estimation attempt
    no-op against a still-TRUSTED sensor and get marked executed, leaving nothing to
    retry once the quarantine that follows it actually lands.
    """
    gateway = TrustedDataGateway()
    _trust_feeders(gateway, {FEEDERS[0]: 12.5, FEEDERS[1]: 12.5, FEEDERS[2]: 12.5, FEEDERS[3]: 12.5})

    actions = [
        ResponseAction(type="ENABLE_ESTIMATION_FALLBACK", target=SUBSTATION, risk="LOW", auto_execute=True, executed=False),
        ResponseAction(type="QUARANTINE_SENSOR", target=SUBSTATION, risk="LOW", auto_execute=True, executed=False),
    ]
    response_tools.execute_all(gateway, actions)

    assert gateway.status(SUBSTATION) == "ESTIMATED"
    assert all(a.executed for a in actions)
