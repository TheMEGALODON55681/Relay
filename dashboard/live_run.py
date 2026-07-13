"""Drives one full scenario run tick by tick and keeps a detailed trace for the
Streamlit dashboard: per-tick per-sensor detection scores, agent decisions, final
incident and gateway state, and dispatch cost/emissions. evaluation/harness.py runs
the same underlying pipeline but only keeps aggregate metrics across many runs; this
keeps everything for one run so it can be charted.
"""

from dataclasses import dataclass, field

import numpy as np

from config import settings
from detection.risk_engine import RiskEngine
from evaluation.harness import SCENARIO_SEED_OFFSET, TICKS_PER_RUN, build_attack, tick_readings
from gateway.trusted_data_gateway import TrustedDataGateway
from optimization import optimizer
from schemas.models import AgentDecision, Incident, TelemetryEvent
from simulator.grid import SENSOR_KIND, SUBSTATION, Grid
from soc.incident_manager import IncidentManager
from soc.orchestrator import run_incident

TICK_HOURS = settings.TICK_SECONDS / 3600


@dataclass
class RunTrace:
    scenario: str
    security_enabled: bool
    detection_rows: list[dict] = field(default_factory=list)
    dispatch_rows: list[dict] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    decisions: list[AgentDecision] = field(default_factory=list)
    gateway_status: dict[str, str] = field(default_factory=dict)
    gateway_reasons: dict[str, str] = field(default_factory=dict)
    total_cost: float = 0.0
    total_emissions: float = 0.0
    total_unnecessary_mwh: float = 0.0


def _process_sensor(event: TelemetryEvent, true_load: float, risk_engine: RiskEngine, manager: IncidentManager, gateway: TrustedDataGateway, tick: int, trace: RunTrace) -> None:
    detection = risk_engine.evaluate(event)
    trace.detection_rows.append(
        {
            "tick": tick,
            "sensor_id": event.sensor_id,
            "rule_score": detection.rule_score,
            "statistical_score": detection.statistical_score,
            "ml_score": detection.ml_score,
            "physics_score": detection.physics_score,
            "risk_score": detection.risk_score,
            "classification": detection.classification,
            "is_attacked": event.is_attacked,
        }
    )
    if detection.trigger_soc_workflow and trace.security_enabled:
        incident = manager.handle_detection(event.sensor_id, event.asset_id, detection)
        if incident is not None:
            trace.decisions.extend(run_incident(incident, manager, gateway))

    if trace.security_enabled:
        # Every sensor's latest trusted reading, not just the substation's -
        # constraint reconstruction needs a feeder's own last-known-good value to
        # solve for a different feeder.
        gateway.record(event)

    if event.sensor_id != SUBSTATION:
        return
    dispatched_load = gateway.resolve_load(event) if trace.security_enabled else event.load
    cost = emissions = None
    if dispatched_load is not None:
        dispatch = optimizer.dispatch(dispatched_load)
        cost, emissions = dispatch["cost"], dispatch["emissions"]
        trace.total_cost += cost
        trace.total_emissions += emissions
    reference = true_load if dispatched_load is None else dispatched_load
    trace.total_unnecessary_mwh += abs(reference - true_load) * TICK_HOURS
    trace.dispatch_rows.append({"tick": tick, "true_load": true_load, "reported_load": event.load, "dispatched_load": dispatched_load, "cost": cost, "emissions": emissions})


def run_live(scenario: str, security_enabled: bool, seed: int = settings.RANDOM_SEED, snapshot_tick: int | None = None) -> RunTrace:
    """Runs `scenario` once (LOAD_INFLATION, LOAD_SUPPRESSION, COORDINATED_FDI, or the
    demonstration-only ESCALATING_FDI) with the same seed, tick count, and attack
    calibration the evaluation harness uses, so a dashboard run and a harness run of
    the same scenario are directly comparable.

    snapshot_tick freezes the reported gateway status/reason at that tick instead of
    the run's final tick - ESCALATING_FDI's interesting moment (all three trust states
    at once) is transient and would otherwise be overwritten by the later stages that
    degrade it further.
    """
    full_seed = seed + SCENARIO_SEED_OFFSET[scenario]
    attack = build_attack(scenario, np.random.default_rng(full_seed))
    grid = Grid(seed=full_seed)
    risk_engine = RiskEngine()
    gateway = TrustedDataGateway()
    manager = IncidentManager(db_path=":memory:")
    trace = RunTrace(scenario=scenario, security_enabled=security_enabled)
    snapshot: dict[str, tuple] | None = None

    for tick in range(TICKS_PER_RUN):
        readings, true_load = tick_readings(grid, attack, tick)
        for raw in readings:
            _process_sensor(TelemetryEvent(**raw), true_load, risk_engine, manager, gateway, tick, trace)
        if tick == snapshot_tick:
            snapshot = {s: gateway.status_of(s) for s in SENSOR_KIND}

    incident_ids = {d.incident_id for d in trace.decisions}
    trace.incidents = [manager.get(i) for i in incident_ids]
    final = snapshot if snapshot is not None else {s: gateway.status_of(s) for s in SENSOR_KIND}
    trace.gateway_status = {s: state.value for s, (state, _reason) in final.items()}
    trace.gateway_reasons = {s: reason for s, (_state, reason) in final.items()}
    trace.total_cost = round(trace.total_cost, 4)
    trace.total_emissions = round(trace.total_emissions, 5)
    trace.total_unnecessary_mwh = round(trace.total_unnecessary_mwh, 6)
    manager.close()
    return trace
