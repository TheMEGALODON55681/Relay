"""Converts one grid tick into per-sensor telemetry dicts, ready for ingestion."""

from dataclasses import asdict
from datetime import datetime, timezone

from simulator.grid import Grid


def emit_tick(grid: Grid) -> list[dict]:
    timestamp = datetime.now(timezone.utc)
    return [asdict(r) | {"timestamp": timestamp, "is_attacked": False} for r in grid.step()]
