"""Bridges detection/response to the optimizer. Every sensor stream is labeled
TRUSTED, ESTIMATED, or QUARANTINED; the optimizer may only ever read a TRUSTED or
ESTIMATED value, never a quarantined sensor's raw reading. This is the mechanism
that enforces the project's central thesis: verify before optimizing.
"""

from optimization import fallback
from schemas.models import TelemetryEvent


class TrustedDataGateway:
    def __init__(self) -> None:
        self._status: dict[str, str] = {}
        self._history: dict[str, list[TelemetryEvent]] = {}

    def status(self, sensor_id: str) -> str:
        return self._status.get(sensor_id, "TRUSTED")

    def record(self, event: TelemetryEvent) -> None:
        """Call after the detection/containment decision for this event, not before -
        this event's own status only reflects that decision once it's been made. Only
        learns from the reading while the sensor is TRUSTED at call time, so a sensor's
        history (and any estimate built from it) never absorbs a poisoned or
        already-quarantined reading, even across several poisoned ticks before
        containment reacts.
        """
        if self.status(event.sensor_id) != "TRUSTED":
            return
        history = self._history.setdefault(event.sensor_id, [])
        history.append(event)
        del history[: -fallback.HISTORY_WINDOW]

    def quarantine(self, sensor_id: str) -> None:
        """Blocks the raw reading. A no-op if the sensor already has a working estimate
        - the fixed containment playbooks (quarantine, enable_estimation, freeze) always
        fire together in that order, and a later "stop trusting" action must not undo the
        estimation fallback the previous one just enabled.
        """
        if self.status(sensor_id) != "ESTIMATED":
            self._status[sensor_id] = "QUARANTINED"

    def enable_estimation(self, sensor_id: str) -> None:
        self._status[sensor_id] = "ESTIMATED"

    def resolve_load(self, event: TelemetryEvent) -> float | None:
        """The load value the optimizer is allowed to use for this sensor this tick.
        None means withhold: quarantined with no estimation fallback enabled yet.
        """
        status = self.status(event.sensor_id)
        if status == "TRUSTED":
            return event.load
        if status == "ESTIMATED":
            return fallback.estimate(self._history.get(event.sensor_id, []))
        return None
