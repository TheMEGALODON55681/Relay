"""Runs the Relay telemetry pipeline on the console: simulator -> ingestion ->
hybrid detection engine -> incident manager -> agentic SOC -> trusted data gateway ->
optimizer stub. A triggered detection quarantines its sensor and substitutes a trusted
estimate before dispatch, so the optimizer never sees a manipulated reading.
"""

import asyncio

from automation.event_bus import EventBus
from config import settings
from detection.risk_engine import RiskEngine
from gateway.trusted_data_gateway import TrustedDataGateway
from ingestion import service as ingestion_service
from optimization import optimizer
from simulator.grid import SUBSTATION, Grid
from simulator.telemetry import emit_tick
from soc.incident_manager import IncidentManager
from soc.orchestrator import run_incident

TICKS = 15
INJECT_AT_TICK = 8


async def _simulate(bus: EventBus) -> None:
    grid = Grid()
    for t in range(1, TICKS + 1):
        readings = emit_tick(grid)
        for reading in readings:
            if t == INJECT_AT_TICK and reading["asset_id"] == SUBSTATION:
                reading["voltage"] *= 1.3
                reading["load"] *= 1.6
                print(f"[tick {t}] manually injecting an out-of-range reading on {reading['sensor_id']}")
            await bus.publish(ingestion_service.RAW_TOPIC, reading)
        await asyncio.sleep(settings.TICK_SECONDS)
    await bus.publish(ingestion_service.RAW_TOPIC, None)


async def _detect_and_dispatch(clean_queue: asyncio.Queue, manager: IncidentManager, gateway: TrustedDataGateway) -> None:
    risk_engine = RiskEngine()
    while True:
        event = await clean_queue.get()
        if event is None:
            return
        result = risk_engine.evaluate(event)
        if result.trigger_soc_workflow:
            print(
                f"ALERT sensor={event.sensor_id} risk_score={result.risk_score:.2f} "
                f"classification={result.classification} evidence={result.evidence}"
            )
            incident = manager.handle_detection(event.sensor_id, event.asset_id, result)
            if incident is not None:
                run_incident(incident, manager, gateway)
                print(f"INCIDENT {incident.incident_id} -> {incident.status}")

        if event.asset_id == SUBSTATION:
            load = gateway.resolve_load(event)
            if load is not None:
                dispatch = optimizer.dispatch(load)
                print(f"DISPATCH sensor={event.sensor_id} -> {dispatch}")
            else:
                print(f"DISPATCH sensor={event.sensor_id} -> withheld (quarantined, no estimate yet)")
        gateway.record(event)


async def run() -> None:
    bus = EventBus()
    manager = IncidentManager()
    gateway = TrustedDataGateway()
    # Subscribe before anything publishes, so no tick is lost to scheduling order.
    raw_queue = bus.subscribe(ingestion_service.RAW_TOPIC)
    clean_queue = bus.subscribe(ingestion_service.CLEAN_TOPIC)
    await asyncio.gather(
        _simulate(bus),
        ingestion_service.run(bus, raw_queue),
        _detect_and_dispatch(clean_queue, manager, gateway),
    )
    manager.close()


if __name__ == "__main__":
    asyncio.run(run())
