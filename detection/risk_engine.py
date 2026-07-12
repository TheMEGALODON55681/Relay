"""Unified risk scoring: combines the four detector scores into one number and
classifies it. No single detector triggers a workflow on its own; only the unified
score does.
"""

import uuid

from config import settings
from detection import ml_detector, physics_validator, rule_engine, statistical_detector
from detection.sensor_history import DetectionContext, SensorHistory
from schemas.models import DetectionResult, TelemetryEvent
from simulator.grid import BATTERY, SUBSTATION

# The only two asset kinds physics_validator can compute fresh evidence for: they are
# late enough in a tick's reporting order to see every peer's current-tick reading.
# Relies on the simulator's guarantee that every sensor in a tick shares one timestamp
# and reports in a fixed order (simulator/telemetry.py, simulator/grid.py); a live feed
# with per-reading jitter or dropped sensors would need an explicit tick/cycle id instead.
_PHYSICS_SOURCE_ASSETS = (SUBSTATION, BATTERY)


def _classify(score: float) -> str:
    label = settings.RISK_BANDS[0][1]
    for lower_bound, name in settings.RISK_BANDS:
        if score >= lower_bound:
            label = name
    return label


class RiskEngine:
    def __init__(self) -> None:
        self._history = SensorHistory()
        # Sensors evaluated earlier in a tick's reporting order (generators, feeders) reuse
        # the strongest substation+battery physics result from the last completed tick,
        # instead of getting no physics signal at all. _this_tick accumulates the max of the
        # substation and battery checks as they report (each can find a different violation);
        # _last_tick is what earlier-order sensors see, swapped in wholesale once a new tick
        # starts so a resolved condition clears instead of pinning every sensor forever.
        self._last_tick_physics: tuple[float, dict] = (0.0, {})
        self._this_tick_physics: tuple[float, dict] = (0.0, {})
        self._tick_timestamp = None

    def evaluate(self, event: TelemetryEvent) -> DetectionResult:
        ctx = self._history.push(event)
        self._roll_tick_if_new(event)

        rule_score, rule_evidence = rule_engine.evaluate(ctx)
        statistical_score, statistical_evidence = statistical_detector.evaluate(ctx)
        ml_score, ml_evidence = ml_detector.evaluate(ctx)
        physics_score, physics_evidence = self._resolve_physics(ctx)

        risk_score = round(
            settings.RULE_WEIGHT * rule_score
            + settings.STATISTICAL_WEIGHT * statistical_score
            + settings.ML_WEIGHT * ml_score
            + settings.PHYSICS_WEIGHT * physics_score,
            4,
        )

        return DetectionResult(
            event_id=str(uuid.uuid4()),
            sensor_id=event.sensor_id,
            rule_score=round(rule_score, 4),
            statistical_score=round(statistical_score, 4),
            ml_score=round(ml_score, 4),
            physics_score=round(physics_score, 4),
            risk_score=risk_score,
            classification=_classify(risk_score),
            evidence={
                "rule": rule_evidence,
                "statistical": statistical_evidence,
                "ml": ml_evidence,
                "physics": physics_evidence,
            },
            trigger_soc_workflow=risk_score >= settings.WORKFLOW_TRIGGER_MIN_SCORE,
        )

    def _roll_tick_if_new(self, event: TelemetryEvent) -> None:
        if event.timestamp != self._tick_timestamp:
            self._last_tick_physics = self._this_tick_physics
            self._this_tick_physics = (0.0, {})
            self._tick_timestamp = event.timestamp

    def _resolve_physics(self, ctx: DetectionContext) -> tuple[float, dict]:
        if ctx.event.asset_id not in _PHYSICS_SOURCE_ASSETS:
            return self._last_tick_physics
        fresh_score, fresh_evidence = physics_validator.evaluate(ctx)
        self._this_tick_physics = (
            max(fresh_score, self._this_tick_physics[0]),
            {**self._this_tick_physics[1], **fresh_evidence},
        )
        return self._this_tick_physics
