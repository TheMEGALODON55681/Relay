"""Runs each attack scenario N times (default 30) plus a normal baseline, security ON
and OFF, and logs one EvaluationRun per run. Drives the simulator/detection/incident/
agent/gateway pipeline directly and synchronously - no event bus, no sleeping - so a
full harness run completes without depending on wall-clock tick pacing. Reproducible
under a fixed seed: every random draw (grid noise, attack parameters) is derived from
settings.RANDOM_SEED plus a fixed per-scenario offset and the run index. Output
aggregation and file writing lives in evaluation/report.py.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from config import settings
from detection.risk_engine import RiskEngine
from evaluation import report
from gateway.trusted_data_gateway import TrustedDataGateway
from optimization import optimizer
from schemas.models import EvaluationRun, TelemetryEvent
from simulator.attacks.base import Attack
from simulator.attacks.coordinated_fdi import CoordinatedFdiAttack
from simulator.attacks.load_inflation import LoadInflationAttack
from simulator.attacks.load_suppression import LoadSuppressionAttack
from simulator.grid import FEEDERS, SUBSTATION, Grid
from soc.incident_manager import IncidentManager
from soc.orchestrator import run_incident

TICKS_PER_RUN = 50
# Must exceed ROLLING_WINDOW_TICKS so the statistical detector has a stable baseline
# (full rolling window) before onset - a short warm-up inflates false positives from an
# unstable, sample-starved rolling std, not genuine detector noise.
ATTACK_START_TICK = settings.ROLLING_WINDOW_TICKS + 5
TICK_HOURS = settings.TICK_SECONDS / 3600
SCENARIOS = ("LOAD_INFLATION", "LOAD_SUPPRESSION", "COORDINATED_FDI")
SCENARIO_SEED_OFFSET = {"LOAD_INFLATION": 0, "LOAD_SUPPRESSION": 1000, "COORDINATED_FDI": 2000, "BASELINE": 3000}


class _NoAttack(Attack):
    name = "NONE"

    def apply(self, readings: list[dict], tick: int) -> None:
        pass


def build_attack(scenario: str, rng: np.random.Generator) -> Attack:
    if scenario == "LOAD_INFLATION":
        return LoadInflationAttack(SUBSTATION, ATTACK_START_TICK, multiplier=float(rng.uniform(1.35, 1.75)))
    if scenario == "LOAD_SUPPRESSION":
        return LoadSuppressionAttack(SUBSTATION, ATTACK_START_TICK, multiplier=float(rng.uniform(0.45, 0.75)))
    # Signs fixed (3 feeders over-report, 1 under-reports - matching the verified
    # PRD Section 6 example), only magnitudes randomized. Independent random signs per
    # feeder can cancel out to a near-zero net aggregate mismatch, which is individually
    # plausible but defeats the scenario: physics/ML must see a real substation imbalance.
    signs = (1.0, 1.0, 1.0, -1.0)
    shifts = {f: 1.0 + sign * rng.uniform(0.05, 0.10) for f, sign in zip(FEEDERS, signs)}
    return CoordinatedFdiAttack(ATTACK_START_TICK, shifts=shifts)


class _RunTracker:
    """Accumulates the metrics for one simulated run as ticks are processed."""

    def __init__(self, security_enabled: bool):
        self.security_enabled = security_enabled
        self.first_alert_tick: int | None = None
        self.first_containment_tick: int | None = None
        self.false_positive = False
        self.total_cost = 0.0
        self.total_emissions = 0.0
        self.total_unnecessary_mwh = 0.0
        # Pre-onset readings and how many triggered - PRD Section 9's false-positive
        # rate is "fraction of normal windows [readings] classified SUSPICIOUS or
        # above," a per-reading rate, not "did this whole run ever misfire once."
        self.pre_onset_readings = 0
        self.pre_onset_triggers = 0

    def note_detection(self, tick: int, triggered: bool) -> None:
        if tick < ATTACK_START_TICK:
            self.pre_onset_readings += 1
        if not triggered:
            return
        if tick < ATTACK_START_TICK:
            self.pre_onset_triggers += 1
            self.false_positive = True
        elif self.first_alert_tick is None:
            self.first_alert_tick = tick

    def note_containment(self, tick: int, contained: bool) -> None:
        """Only counts containment at or after attack onset - a pre-onset false
        positive can trigger its own (unrelated) containment, which must not read as
        "containment before detection" once the real attack's alert lands later.
        """
        if contained and tick >= ATTACK_START_TICK and self.first_containment_tick is None:
            self.first_containment_tick = tick

    def note_dispatch(self, dispatched_load: float | None, true_load: float) -> None:
        if dispatched_load is not None:
            dispatch = optimizer.dispatch(dispatched_load)
            self.total_cost += dispatch["cost"]
            self.total_emissions += dispatch["emissions"]
        reference = true_load if dispatched_load is None else dispatched_load
        self.total_unnecessary_mwh += abs(reference - true_load) * TICK_HOURS

    def as_dict(self) -> dict:
        latency = None if self.first_alert_tick is None else self.first_alert_tick - ATTACK_START_TICK
        containment = None
        if self.security_enabled and self.first_alert_tick is not None and self.first_containment_tick is not None:
            containment = self.first_containment_tick - self.first_alert_tick
        return {
            "attack_detected": self.first_alert_tick is not None,
            "detection_latency_ticks": latency,
            "containment_latency_ticks": containment,
            "dispatch_cost": round(self.total_cost, 4),
            "dispatch_emissions": round(self.total_emissions, 5),
            "unnecessary_generation_mwh": round(self.total_unnecessary_mwh, 6),
            "false_positive": self.false_positive,
        }


def tick_readings(grid: Grid, attack: Attack, tick: int) -> tuple[list[dict], float]:
    timestamp = datetime.now(timezone.utc)
    readings = [asdict(r) | {"timestamp": timestamp, "is_attacked": False} for r in grid.step()]
    true_load = next(r["load"] for r in readings if r["sensor_id"] == SUBSTATION)
    attack.apply(readings, tick)
    return readings, true_load


def _handle_alert(event: TelemetryEvent, detection, manager: IncidentManager, gateway: TrustedDataGateway, tick: int, tracker: _RunTracker) -> None:
    incident = manager.handle_detection(event.sensor_id, event.asset_id, detection)
    if incident is None:
        return
    run_incident(incident, manager, gateway)
    contained = any(a.executed for a in incident.response_actions)
    tracker.note_containment(tick, contained)


def _dispatch_substation(event: TelemetryEvent, gateway: TrustedDataGateway | None, security_enabled: bool, true_load: float, tracker: _RunTracker) -> None:
    dispatched_load = gateway.resolve_load(event) if security_enabled else event.load
    if security_enabled:
        gateway.record(event)
    tracker.note_dispatch(dispatched_load, true_load)


def _simulate(attack: Attack, grid_seed: int, security_enabled: bool) -> _RunTracker:
    grid = Grid(seed=grid_seed)
    risk_engine = RiskEngine()
    gateway = TrustedDataGateway() if security_enabled else None
    manager = IncidentManager(db_path=":memory:") if security_enabled else None
    tracker = _RunTracker(security_enabled)

    for tick in range(TICKS_PER_RUN):
        readings, true_load = tick_readings(grid, attack, tick)
        for raw in readings:
            event = TelemetryEvent(**raw)
            detection = risk_engine.evaluate(event)
            tracker.note_detection(tick, detection.trigger_soc_workflow)
            if detection.trigger_soc_workflow and security_enabled:
                _handle_alert(event, detection, manager, gateway, tick, tracker)
            if event.sensor_id == SUBSTATION:
                _dispatch_substation(event, gateway, security_enabled, true_load, tracker)

    if manager is not None:
        manager.close()
    return tracker


def run_harness(n_runs: int = settings.EVAL_RUNS_PER_SCENARIO, out_dir: str = settings.RESULTS_DIR) -> list[EvaluationRun]:
    runs: list[EvaluationRun] = []
    for scenario in SCENARIOS:
        for run_index in range(n_runs):
            seed = settings.RANDOM_SEED + SCENARIO_SEED_OFFSET[scenario] + run_index
            attack = build_attack(scenario, np.random.default_rng(seed))
            for security_enabled in (True, False):
                tracker = _simulate(attack, seed, security_enabled)
                runs.append(EvaluationRun(scenario=scenario, run_index=run_index, security_enabled=security_enabled, **tracker.as_dict()))

    pre_onset_readings = pre_onset_triggers = 0
    for run_index in range(n_runs):
        seed = settings.RANDOM_SEED + SCENARIO_SEED_OFFSET["BASELINE"] + run_index
        tracker = _simulate(_NoAttack(), seed, security_enabled=True)
        runs.append(EvaluationRun(scenario="BASELINE", run_index=run_index, security_enabled=True, **tracker.as_dict()))
        pre_onset_readings += tracker.pre_onset_readings
        pre_onset_triggers += tracker.pre_onset_triggers

    report.write_outputs(runs, Path(out_dir), pre_onset_readings, pre_onset_triggers)
    return runs


if __name__ == "__main__":
    run_harness()
