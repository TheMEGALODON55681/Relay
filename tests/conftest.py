"""Shared test builders: crafted TelemetryEvent and DetectionContext instances."""

from datetime import datetime, timedelta, timezone

from config import settings
from detection.sensor_history import DetectionContext
from schemas.models import TelemetryEvent

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_event(sensor_id: str = "FEEDER-1", asset_id: str | None = None, tick: int = 0, **overrides) -> TelemetryEvent:
    defaults = dict(
        sensor_id=sensor_id,
        asset_id=asset_id or sensor_id,
        timestamp=BASE_TIME + timedelta(seconds=tick * settings.TICK_SECONDS),
        voltage=settings.VOLTAGE_NOMINAL,
        current=50.0,
        frequency=settings.FREQUENCY_NOMINAL,
        active_power=12.5,
        reactive_power=3.0,
        power_factor=0.95,
        load=12.5,
        generation=0.0,
        battery_soc=50.0,
        is_attacked=False,
    )
    defaults.update(overrides)
    return TelemetryEvent(**defaults)


def make_context(
    event: TelemetryEvent,
    series: list[TelemetryEvent] | None = None,
    snapshot: dict[str, TelemetryEvent] | None = None,
) -> DetectionContext:
    return DetectionContext(
        event=event,
        series=series or [event],
        snapshot=snapshot or {event.sensor_id: event},
    )
