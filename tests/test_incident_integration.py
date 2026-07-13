"""Integration test: one full incident from telemetry to safe dispatch. Proves a
poisoned reading is quarantined and the optimizer receives the reconstructed value,
never the manipulated one (PRD Section 11).
"""

import uuid

import numpy as np

from config import settings
from detection.risk_engine import RiskEngine
from evaluation.harness import (
    ATTACK_START_TICK,
    ESCALATING_FDI_DEMO_SEED,
    ESCALATING_FDI_SNAPSHOT_TICK,
    SCENARIO_SEED_OFFSET,
    TICKS_PER_RUN,
    _dispatch_substation,
    _RunTracker,
    build_attack,
    tick_readings,
)
from gateway.trusted_data_gateway import TrustedDataGateway
from optimization import optimizer
from schemas.models import DetectionResult, TelemetryEvent
from simulator.grid import BATTERY, FEEDERS, GENERATORS, SUBSTATION, Grid
from soc.incident_manager import IncidentManager
from soc.orchestrator import run_incident
from tests.conftest import make_event


def _seed_trusted_baseline(gateway: TrustedDataGateway, substation_load: float = 50.0, ticks: int = 10) -> None:
    """Records substation_load / 4 for each feeder alongside the substation's own
    load for `ticks` ticks, so every member of SUBSTATION_AGGREGATION has a recent
    TRUSTED reading to reconstruct from. Real load holds steady; a poisoned reading
    is never recorded here - record() is only ever called after containment reacts.
    """
    feeder_load = substation_load / len(FEEDERS)
    for tick in range(ticks):
        gateway.record(make_event(sensor_id=SUBSTATION, asset_id=SUBSTATION, tick=tick, load=substation_load))
        for feeder in FEEDERS:
            gateway.record(make_event(sensor_id=feeder, asset_id=feeder, tick=tick, load=feeder_load))


def test_poisoned_reading_never_reaches_the_optimizer(tmp_path):
    gateway = TrustedDataGateway()
    manager = IncidentManager(db_path=str(tmp_path / "incident.db"))

    _seed_trusted_baseline(gateway, substation_load=50.0)

    # Load inflation attack: reported 90 MW against a true ~50 MW (PRD Section 6 example).
    # Not recorded into the gateway's history - a poisoned reading must never become
    # part of what a peer's "last known good" is computed from.
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

    # All 4 feeders are still TRUSTED - the substation is the sole unknown in
    # SUBSTATION_AGGREGATION, so it reconstructs exactly rather than staying withheld.
    assert gateway.status(poisoned.sensor_id) == "ESTIMATED"
    resolved_load = gateway.resolve_load(poisoned)
    assert resolved_load is not None, "optimizer input must not be silently dropped once estimation succeeds"
    assert resolved_load != poisoned.load, "the manipulated 90 MW reading must never reach the optimizer"
    assert abs(resolved_load - 50.0) < 1e-6, "the reconstruction should exactly match the trusted feeder sum"

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
    _seed_trusted_baseline(gateway, substation_load=50.0)

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
    # is still held - it's CRITICAL-only. All 4 feeders are untouched by this incident,
    # so ENABLE_ESTIMATION_FALLBACK succeeds: the substation is the sole unknown.
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
    proposed only for that sensor's asset. When a real attack on a DIFFERENT asset in
    the SAME constraint correlates into the same incident afterward, that asset must
    also end up covered by containment - not silently left TRUSTED because the original
    proposal never named it (evaluation/harness.py surfaced this: a pre-attack false
    positive on one sensor was leaving the real attack's sensor unprotected).

    Both sensors here belong to SUBSTATION_AGGREGATION, so once both are compromised
    the constraint has two unknowns for one equation: genuinely underdetermined. Under
    THE ONE RULE neither can borrow the other as a trusted source, so "protected" now
    correctly means QUARANTINED (nothing served) rather than a false ESTIMATED value -
    the fix this PRD exists for.
    """
    gateway = TrustedDataGateway()
    manager = IncidentManager(db_path=str(tmp_path / "incident4.db"))
    _seed_trusted_baseline(gateway, substation_load=50.0)

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
    assert gateway.status("FEEDER-1") == "TRUSTED"

    # The real attack lands on SUBSTATION and correlates into the same incident.
    second = manager.handle_detection(SUBSTATION, SUBSTATION, _detection(SUBSTATION, "HIGH_RISK"))
    assert second.incident_id == first.incident_id
    run_incident(second, manager, gateway)

    saved = manager.get(first.incident_id)
    assert SUBSTATION in saved.affected_assets
    substation_actions = [a for a in saved.response_actions if a.target == SUBSTATION]
    assert {"QUARANTINE_SENSOR", "ENABLE_ESTIMATION_FALLBACK", "FREEZE_OPTIMIZATION_INPUT"} <= {a.type for a in substation_actions}
    assert all(a.executed for a in substation_actions if a.type == "QUARANTINE_SENSOR")
    # Neither sensor is left TRUSTED - both are protected - but with two of the
    # constraint's five members compromised, neither can be reconstructed from the
    # other, so both terminate QUARANTINED rather than one being falsely ESTIMATED.
    assert gateway.status(SUBSTATION) == "QUARANTINED"
    assert gateway.status("FEEDER-1") == "QUARANTINED"
    assert gateway.resolve_load(make_event(sensor_id=SUBSTATION, load=90.0)) is None

    manager.close()


def test_coordinated_fdi_reaches_quarantined_state(tmp_path):
    """Real seeded COORDINATED_FDI run (seed 2047, run_index 5 of the evaluation
    harness's own scenario/seed scheme) through the actual simulator, detection, and
    SOC pipeline: the four feeders get shifted together, escalate to HIGH_RISK, and
    the incident's containment quarantines all of them at once - four unknowns for one
    equation, the degradation case THE ONE RULE exists for.
    """
    run_index = 5
    seed = settings.RANDOM_SEED + SCENARIO_SEED_OFFSET["COORDINATED_FDI"] + run_index
    attack = build_attack("COORDINATED_FDI", np.random.default_rng(seed))
    grid = Grid(seed=seed)
    risk_engine = RiskEngine()
    gateway = TrustedDataGateway()
    manager = IncidentManager(db_path=str(tmp_path / "coordinated.db"))

    reached_high_risk = False
    for tick in range(TICKS_PER_RUN):
        readings, _true_load = tick_readings(grid, attack, tick)
        for raw in readings:
            event = TelemetryEvent(**raw)
            detection = risk_engine.evaluate(event)
            reached_high_risk = reached_high_risk or detection.classification in ("HIGH_RISK", "CRITICAL")
            if detection.trigger_soc_workflow:
                incident = manager.handle_detection(event.sensor_id, event.asset_id, detection)
                if incident is not None:
                    run_incident(incident, manager, gateway)
            gateway.record(event)
    manager.close()

    assert reached_high_risk, "this seed is expected to escalate past SUSPICIOUS"
    quarantined = [s for s in FEEDERS if gateway.status(s) == "QUARANTINED"]
    assert quarantined, f"expected at least one terminal QUARANTINED sensor, got {[gateway.status(s) for s in FEEDERS]}"


def test_gateway_consumer_handles_none_value(tmp_path):
    """The value consumer (evaluation.harness._dispatch_substation, the same function
    the harness and dashboard both drive off) does not crash and does not coerce None
    into a number when the substation is quarantined with no estimate available.
    """
    gateway = TrustedDataGateway()
    gateway.quarantine(SUBSTATION)  # no feeder baseline recorded - genuinely unobservable

    event = make_event(sensor_id=SUBSTATION, asset_id=SUBSTATION, load=90.0)
    tracker = _RunTracker(security_enabled=True)

    _dispatch_substation(event, gateway, security_enabled=True, true_load=50.0, tracker=tracker)

    assert tracker.total_cost == 0.0
    assert tracker.total_emissions == 0.0
    assert tracker.total_unnecessary_mwh == 0.0


def test_escalating_fdi_demo_seed_shows_all_three_states(tmp_path):
    """Regression check for the dashboard demo (simulator/attacks/escalating_fdi.py):
    at ESCALATING_FDI_DEMO_SEED, ESCALATING_FDI_SNAPSHOT_TICK is the one frame where
    TRUSTED, ESTIMATED, and QUARANTINED are all present - the exact capture
    gateway-states.png relies on. Not every seed produces this; if a future change to
    detection or the gateway breaks it, this is the test that should catch it.
    """
    from simulator.attacks.escalating_fdi import EscalatingFdiAttack

    full_seed = ESCALATING_FDI_DEMO_SEED + SCENARIO_SEED_OFFSET["ESCALATING_FDI"]
    attack = EscalatingFdiAttack(ATTACK_START_TICK)
    grid = Grid(seed=full_seed)
    risk_engine = RiskEngine()
    gateway = TrustedDataGateway()
    manager = IncidentManager(db_path=str(tmp_path / "escalating.db"))

    for tick in range(ESCALATING_FDI_SNAPSHOT_TICK + 1):
        readings, _true_load = tick_readings(grid, attack, tick)
        for raw in readings:
            event = TelemetryEvent(**raw)
            detection = risk_engine.evaluate(event)
            if detection.trigger_soc_workflow:
                incident = manager.handle_detection(event.sensor_id, event.asset_id, detection)
                if incident is not None:
                    run_incident(incident, manager, gateway)
            gateway.record(event)
    manager.close()

    states = {gateway.status(s) for s in (*GENERATORS, *FEEDERS, SUBSTATION, BATTERY)}
    assert {"TRUSTED", "ESTIMATED", "QUARANTINED"} <= states, states
    assert gateway.status(GENERATORS[0]) == "QUARANTINED", "the generator has no constraint - never reconstructable"
    assert gateway.status(SUBSTATION) == "ESTIMATED", "sole unknown in SUBSTATION_AGGREGATION at this tick"


def test_escalating_fdi_excluded_from_evaluation():
    """Hard guardrail (PRD Phase 3.5): ESCALATING_FDI is demonstration-only. SCENARIOS
    is the only scenario list evaluation.harness's run_harness() iterates, and
    ab_compare.compare() only ever sees EvaluationRun objects that harness produced from
    it - so this one assertion structurally guarantees ESCALATING_FDI reaches neither.
    If a future change ever calls ab_compare.compare() from a second, non-SCENARIOS-
    driven call site, this test would no longer be sufficient on its own.
    """
    from evaluation.harness import SCENARIOS

    assert "ESCALATING_FDI" not in SCENARIOS
    assert SCENARIOS == ("LOAD_INFLATION", "LOAD_SUPPRESSION", "COORDINATED_FDI")
