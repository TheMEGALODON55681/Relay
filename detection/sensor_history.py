"""Per-sensor rolling history and the shared per-event context built from it.

Used by all four detectors: rule engine, statistical detector, ML feature builder,
and physics validator.
"""

from collections import defaultdict, deque
from dataclasses import dataclass

from config import settings
from schemas.models import TelemetryEvent


@dataclass
class DetectionContext:
    event: TelemetryEvent
    series: list[TelemetryEvent]  # this sensor's rolling window, oldest first, current last
    snapshot: dict[str, TelemetryEvent]  # most recent reading seen so far for every sensor

    @property
    def previous(self) -> TelemetryEvent | None:
        return self.series[-2] if len(self.series) >= 2 else None


class SensorHistory:
    """Sensors within one tick are evaluated one at a time as they stream in, so a sensor
    early in the reporting order (generators) sees peers (feeders, battery) that haven't
    reported this tick yet. Cross-sensor checks that need same-tick data (physics_validator,
    rule_engine) account for this by only firing once the topology guarantees every needed
    peer has already reported: see the asset_id guards in those checks.
    """

    def __init__(self, window: int = settings.ROLLING_WINDOW_TICKS) -> None:
        self._series: dict[str, deque[TelemetryEvent]] = defaultdict(lambda: deque(maxlen=window))
        self._latest: dict[str, TelemetryEvent] = {}

    def push(self, event: TelemetryEvent) -> DetectionContext:
        self._series[event.sensor_id].append(event)
        self._latest[event.sensor_id] = event
        return DetectionContext(
            event=event,
            series=list(self._series[event.sensor_id]),
            snapshot=dict(self._latest),
        )
