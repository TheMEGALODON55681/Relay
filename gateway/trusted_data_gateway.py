"""Bridges detection/response to the optimizer. Every sensor stream is labeled
TRUSTED, ESTIMATED, or QUARANTINED; the optimizer may only ever read a TRUSTED or
ESTIMATED value, never a quarantined sensor's raw reading. This is the mechanism
that enforces the project's central thesis: verify before optimizing.

Observability rule: a quarantined sensor is reconstructable if and only if it is the
single unknown in a constraint (simulator.grid.CONSTRAINTS) where every other member
is currently TRUSTED. One equation solves for exactly one unknown; two or more
unknowns in the same constraint is underdetermined, and the sensor stays QUARANTINED
with nothing served rather than a guess.
"""

from schemas.models import EstimationResult, SensorState, TelemetryEvent
from simulator import grid


class TrustedDataGateway:
    def __init__(self) -> None:
        self._status: dict[str, SensorState] = {}
        self._reasons: dict[str, str] = {}
        self._latest_trusted: dict[str, TelemetryEvent] = {}

    def status(self, sensor_id: str) -> SensorState:
        return self._status.get(sensor_id, SensorState.TRUSTED)

    def status_of(self, sensor_id: str) -> tuple[SensorState, str]:
        """Status plus the human-readable reason it got there, for the dashboard's
        Gateway State panel.
        """
        return self.status(sensor_id), self._reasons.get(sensor_id, "trusted: no containment action taken")

    def record(self, event: TelemetryEvent) -> None:
        """Call after the detection/containment decision for this event, not before -
        this event's own status only reflects that decision once it's been made. Only
        learns from the reading while the sensor is TRUSTED at call time, so the
        "latest trusted" value a constraint reconstruction solves from never absorbs a
        poisoned or already-quarantined reading, even across several poisoned ticks
        before containment reacts.
        """
        if self.status(event.sensor_id) != SensorState.TRUSTED:
            return
        self._latest_trusted[event.sensor_id] = event

    def quarantine(self, sensor_id: str) -> None:
        """Blocks the raw reading. A no-op if the sensor already has a working estimate
        - the fixed containment playbooks quarantine and then enable_estimation for the
        same sensor (soc/tools/response_tools.execute_all orders every quarantine-type
        action, including freeze, ahead of estimation), and a later "stop trusting"
        action must not undo the estimation fallback the previous one just enabled.

        A genuine new quarantine (this sensor was not already ESTIMATED) can change
        whether OTHER sensors sharing a constraint with it are still reconstructable,
        so it re-evaluates any ESTIMATED dependents; one may degrade back to
        QUARANTINED if it becomes the second unknown in its constraint.
        """
        if self.status(sensor_id) == SensorState.ESTIMATED:
            return
        self._set(sensor_id, SensorState.QUARANTINED, "quarantined pending estimation")
        self._reevaluate_dependents(sensor_id)

    def enable_estimation(self, sensor_id: str) -> EstimationResult:
        """No-op on a sensor that's still TRUSTED - a correlated alert can propose this
        action for an asset that was never actually quarantined (containment actions
        are proposed per action type across every affected asset, not conditioned on
        that asset's current gateway status), and a TRUSTED sensor's own live reading
        is always better than a peer-reconstructed one.
        """
        if self.status(sensor_id) == SensorState.TRUSTED:
            return EstimationResult(success=True, state=SensorState.TRUSTED, estimate=None, confidence=None, reason="trusted: no estimation needed")
        value, constraint_name = self._reconstruct(sensor_id)
        if value is not None:
            reason = f"observable: single unknown in constraint {constraint_name}"
            self._set(sensor_id, SensorState.ESTIMATED, reason)
            return EstimationResult(success=True, state=SensorState.ESTIMATED, estimate=value, confidence=1.0, reason=reason)
        reason = self._unobservable_reason(sensor_id)
        self._set(sensor_id, SensorState.QUARANTINED, reason)
        return EstimationResult(success=False, state=SensorState.QUARANTINED, estimate=None, confidence=None, reason=reason)

    def resolve_load(self, event: TelemetryEvent) -> float | None:
        """The load value the optimizer is allowed to use for this sensor this tick.
        None means withhold: quarantined, or estimated but no longer reconstructable.
        """
        status = self.status(event.sensor_id)
        if status == SensorState.TRUSTED:
            return event.load
        if status == SensorState.ESTIMATED:
            value, _ = self._reconstruct(event.sensor_id)
            return value
        return None

    def _set(self, sensor_id: str, state: SensorState, reason: str) -> None:
        self._status[sensor_id] = state
        self._reasons[sensor_id] = reason

    def _reevaluate_dependents(self, changed_sensor_id: str) -> None:
        for constraint in grid.CONSTRAINTS_BY_SENSOR.get(changed_sensor_id, []):
            for member in constraint.members:
                if member != changed_sensor_id and self.status(member) == SensorState.ESTIMATED:
                    self.enable_estimation(member)

    def _reconstruct(self, sensor_id: str) -> tuple[float | None, str]:
        """Tries each constraint sensor_id belongs to, in order, and returns the first
        one solvable right now. THE ONE RULE: an ESTIMATED sensor is never a valid
        source for estimating another sensor. Only TRUSTED sources count - so a
        constraint member that is itself ESTIMATED or QUARANTINED makes sensor_id a
        second unknown, not a known, and that constraint can't solve it.
        """
        for constraint in grid.CONSTRAINTS_BY_SENSOR.get(sensor_id, []):
            others = [m for m in constraint.members if m != sensor_id]
            if any(self.status(m) != SensorState.TRUSTED for m in others):
                continue
            known = {m: self._latest_trusted_value(m) for m in others}
            if any(v is None for v in known.values()):
                continue
            return constraint.solve(sensor_id, known), constraint.name
        return None, ""

    def _unobservable_reason(self, sensor_id: str) -> str:
        constraints = grid.CONSTRAINTS_BY_SENSOR.get(sensor_id, [])
        if not constraints:
            return f"unobservable: {sensor_id} is not covered by any reconstruction constraint"
        best = min(constraints, key=lambda c: self._unknown_count(sensor_id, c))
        unknowns = self._unknown_count(sensor_id, best)
        return f"unobservable: {unknowns} unknowns in constraint {best.name}, need 1"

    def _unknown_count(self, sensor_id: str, constraint: grid.Constraint) -> int:
        others = [m for m in constraint.members if m != sensor_id]
        return 1 + sum(1 for m in others if self.status(m) != SensorState.TRUSTED)

    def _latest_trusted_value(self, sensor_id: str) -> float | None:
        event = self._latest_trusted.get(sensor_id)
        return event.load if event is not None else None
