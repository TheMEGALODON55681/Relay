"""Validates raw sensor dicts into TelemetryEvent and republishes clean events."""

import asyncio

from pydantic import ValidationError

from automation.event_bus import EventBus
from schemas.models import TelemetryEvent

RAW_TOPIC = "telemetry.raw"
CLEAN_TOPIC = "telemetry.clean"


async def run(bus: EventBus, raw_queue: asyncio.Queue) -> None:
    while True:
        raw = await raw_queue.get()
        if raw is None:  # sentinel: upstream stream ended
            await bus.publish(CLEAN_TOPIC, None)
            return
        try:
            event = TelemetryEvent(**raw)
        except ValidationError as exc:
            print(f"INGESTION: rejected malformed reading: {exc}")
            continue
        await bus.publish(CLEAN_TOPIC, event)
