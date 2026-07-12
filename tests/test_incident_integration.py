"""Integration test: one full incident from telemetry to safe dispatch. Proves a
poisoned reading is quarantined and the optimizer receives the estimated value,
never the manipulated one (PRD Section 11).
"""

import uuid

from gateway.trusted_data_gateway import TrustedDataGateway
from optimization import optimizer
from schemas.models import DetectionResult
from simulator.grid import SUBSTATION
from soc.incident_manager import IncidentManager
from soc.orchestrator import run_incident
from tests.conftest import make_event


def test_poisoned_reading_never_reaches_the_optimizer(tmp_path):
    gateway = TrustedDataGateway()
    manager = IncidentManager(db_path=str(tmp_path / "incident.db"))

    # Real load holds steady around 50 MW; the gateway needs this history to estimate from.
    for tick in range(10):
        gateway.record(make_event(sensor_id=SUBSTATION, asset_id=SUBSTATION, tick=tick, load=50.0))

    # Load inflation attack: reported 90 MW against a true ~50 MW (PRD Section 6 example).
    # Not recorded into the gateway's history - a poisoned reading must never become
    # part of what "last known good" is computed from.
    poisoned = make_event(sensor_id=SUBSTATION, asset_id=SUBSTATION, tick=10, load=90.0, is_attacked=True)

    detection = DetectionResult(
        event_id=str(uuid.uuid4()),
        sensor_id=poisoned.sensor_id,
        rule_score=0.6,
        statistical_score=0.6,
        ml_score=0.7,
        physics_score=0.8,
        risk_score=0.7,
        classification="HIGH_RISK",
        evidence={"physics": {"POWER_BALANCE": 0.8}},
        trigger_soc_workflow=True,
    )
    incident = manager.handle_detection(poisoned.sensor_id, poisoned.asset_id, detection)
    assert incident is not None

    run_incident(incident, manager, gateway)

    saved = manager.get(incident.incident_id)
    assert saved.status == "CONTAINMENT_PENDING"

    # A quarantine-type action must have been proposed and auto-executed at HIGH_RISK.
    contained = [a for a in saved.response_actions if a.type == "QUARANTINE_SENSOR" and a.executed]
    assert contained, f"expected an executed QUARANTINE_SENSOR action, got {saved.response_actions}"
    assert gateway.status(poisoned.sensor_id) != "TRUSTED"

    resolved_load = gateway.resolve_load(poisoned)
    assert resolved_load is not None, "optimizer input must not be silently dropped once estimation is enabled"
    assert resolved_load != poisoned.load, "the manipulated 90 MW reading must never reach the optimizer"
    assert abs(resolved_load - 50.0) < 5.0, "the estimate should track the true ~50 MW baseline"

    dispatch = optimizer.dispatch(resolved_load)
    assert dispatch["generation_mw"] == round(resolved_load, 3)
    assert dispatch["generation_mw"] != poisoned.load

    manager.close()


def test_a_correlated_second_alert_does_not_restart_the_workflow(tmp_path):
    """A follow-up alert within the correlation window (regardless of asset - see
    incident_manager._find_correlatable, which only checks time, not asset overlap)
    returns the same (already in-flight) incident from handle_detection. Running the
    pipeline again on it must not re-trigger TRIAGING - it's already past that state.
    """
    gateway = TrustedDataGateway()
    manager = IncidentManager(db_path=str(tmp_path / "incident2.db"))

    def _detection(sensor_id: str) -> DetectionResult:
        return DetectionResult(
            event_id=str(uuid.uuid4()),
            sensor_id=sensor_id,
            rule_score=0.6,
            statistical_score=0.6,
            ml_score=0.7,
            physics_score=0.8,
            risk_score=0.7,
            classification="HIGH_RISK",
            evidence={},
            trigger_soc_workflow=True,
        )

    first = manager.handle_detection(SUBSTATION, SUBSTATION, _detection(SUBSTATION))
    run_incident(first, manager, gateway)
    first_status = manager.get(first.incident_id).status
    assert first_status == "CONTAINMENT_PENDING"

    correlated = manager.handle_detection("FEEDER-1", "FEEDER-1", _detection("FEEDER-1"))
    assert correlated.incident_id == first.incident_id  # correlated into the same incident

    decisions = run_incident(correlated, manager, gateway)  # must not raise InvalidTransition
    assert decisions == []
    assert manager.get(first.incident_id).status == "CONTAINMENT_PENDING"

    manager.close()


def test_escalation_by_correlation_still_executes_containment(tmp_path):
    """An incident that starts at a low classification gets its containment actions
    proposed but held (nothing in SUSPICIOUS's autonomy tier matches this attack's
    playbook). A correlated alert that raises the classification must retroactively
    unlock and execute the already-proposed actions - not silently drop them, and not
    re-run the agents or re-propose new ones.
    """
    gateway = TrustedDataGateway()
    manager = IncidentManager(db_path=str(tmp_path / "incident3.db"))

    def _detection(classification: str) -> DetectionResult:
        return DetectionResult(
            event_id=str(uuid.uuid4()),
            sensor_id=SUBSTATION,
            rule_score=0.5,
            statistical_score=0.5,
            ml_score=0.5,
            physics_score=0.5,
            risk_score=0.5,
            classification=classification,
            evidence={},  # no matching indicators -> threat_kb defaults to COORDINATED_FDI,
            # whose playbook includes recalculate_dispatch (CRITICAL-only) alongside the
            # standard containment set.
            trigger_soc_workflow=True,
        )

    incident = manager.handle_detection(SUBSTATION, SUBSTATION, _detection("SUSPICIOUS"))
    run_incident(incident, manager, gateway)
    proposed = manager.get(incident.incident_id).response_actions
    assert {a.type for a in proposed} >= {"QUARANTINE_SENSOR", "ENABLE_ESTIMATION_FALLBACK", "FREEZE_OPTIMIZATION_INPUT", "RECALCULATE_DISPATCH"}
    # SUSPICIOUS's autonomy tier only allows INCREASE_MONITORING/MARK_DATA_UNTRUSTED - the
    # playbook's INCREASE_MONITORING action auto-executes (a no-op tool), everything else is held.
    assert {a.type for a in proposed if a.executed} == {"INCREASE_MONITORING"}
    assert gateway.status(SUBSTATION) == "TRUSTED"

    escalated = manager.handle_detection(SUBSTATION, SUBSTATION, _detection("HIGH_RISK"))
    assert escalated.incident_id == incident.incident_id
    run_incident(escalated, manager, gateway)
    after_high_risk = manager.get(incident.incident_id).response_actions
    executed_types = {a.type for a in after_high_risk if a.executed}
    # executed is one-way: INCREASE_MONITORING from the SUSPICIOUS step stays executed,
    # plus the three containment actions HIGH_RISK newly unlocks. RECALCULATE_DISPATCH
    # is still held - it's CRITICAL-only.
    assert executed_types == {"INCREASE_MONITORING", "QUARANTINE_SENSOR", "ENABLE_ESTIMATION_FALLBACK", "FREEZE_OPTIMIZATION_INPUT"}, executed_types
    assert gateway.status(SUBSTATION) == "ESTIMATED"

    critical = manager.handle_detection(SUBSTATION, SUBSTATION, _detection("CRITICAL"))
    run_incident(critical, manager, gateway)
    after_critical = manager.get(incident.incident_id).response_actions
    dispatch_action = next(a for a in after_critical if a.type == "RECALCULATE_DISPATCH")
    assert dispatch_action.executed, "recalculate_dispatch should only unlock at CRITICAL"

    manager.close()


def test_correlated_new_asset_gets_containment_too(tmp_path):
    """A weak alert on one sensor opens the incident and gets its containment actions
    proposed only for that sensor's asset. When a real attack on a DIFFERENT asset
    correlates into the same incident afterward, that asset must also end up covered by
    containment - not silently left TRUSTED because the original proposal never named
    it (evaluation/harness.py surfaced this: a pre-attack false positive on one sensor
    was leaving the real attack's sensor unprotected).
    """
    gateway = TrustedDataGateway()
    manager = IncidentManager(db_path=str(tmp_path / "incident4.db"))

    def _detection(sensor_id: str, classification: str) -> DetectionResult:
        return DetectionResult(
            event_id=str(uuid.uuid4()),
            sensor_id=sensor_id,
            rule_score=0.5,
            statistical_score=0.5,
            ml_score=0.5,
            physics_score=0.5,
            risk_score=0.5,
            classification=classification,
            evidence={},
            trigger_soc_workflow=True,
        )

    # A weak false positive on FEEDER-1 opens the incident; SUBSTATION isn't involved yet.
    first = manager.handle_detection("FEEDER-1", "FEEDER-1", _detection("FEEDER-1", "SUSPICIOUS"))
    run_incident(first, manager, gateway)
    assert manager.get(first.incident_id).affected_assets == ["FEEDER-1"]
    assert gateway.status(SUBSTATION) == "TRUSTED"

    # The real attack lands on SUBSTATION and correlates into the same incident.
    second = manager.handle_detection(SUBSTATION, SUBSTATION, _detection(SUBSTATION, "HIGH_RISK"))
    assert second.incident_id == first.incident_id
    run_incident(second, manager, gateway)

    saved = manager.get(first.incident_id)
    assert SUBSTATION in saved.affected_assets
    substation_actions = [a for a in saved.response_actions if a.target == SUBSTATION]
    assert {"QUARANTINE_SENSOR", "ENABLE_ESTIMATION_FALLBACK", "FREEZE_OPTIMIZATION_INPUT"} <= {a.type for a in substation_actions}
    assert all(a.executed for a in substation_actions if a.type in {"QUARANTINE_SENSOR", "ENABLE_ESTIMATION_FALLBACK", "FREEZE_OPTIMIZATION_INPUT"})
    assert gateway.status(SUBSTATION) == "ESTIMATED", "the real attack's sensor must end up protected, not left TRUSTED"

    manager.close()
