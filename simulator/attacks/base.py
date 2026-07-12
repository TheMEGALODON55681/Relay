"""Shared interface and helper for attack scenarios. Each attack mutates a tick's raw
telemetry dicts in place (from simulator.telemetry.emit_tick, before ingestion) and marks
the affected readings' ground truth is_attacked=True.
"""

from abc import ABC, abstractmethod


class Attack(ABC):
    name: str

    @abstractmethod
    def apply(self, readings: list[dict], tick: int) -> None:
        """Mutates readings in place for the given tick, if this attack is active."""


def scale_power_fields(reading: dict, multiplier: float) -> None:
    for field in ("load", "generation", "active_power", "reactive_power", "current"):
        reading[field] *= multiplier
    reading["is_attacked"] = True


class ScaledSensorAttack(Attack):
    """Shared shape for single-sensor attacks that scale every power field by one constant
    multiplier from start_tick onward. load_inflation and load_suppression are the same
    mechanism at different multipliers; kept as separate files/classes per the PRD's
    scenario structure, sharing this base to avoid duplicating the mutation logic.
    """

    def __init__(self, target_sensor: str, start_tick: int, multiplier: float):
        self.target_sensor = target_sensor
        self.start_tick = start_tick
        self.multiplier = multiplier

    def apply(self, readings: list[dict], tick: int) -> None:
        if tick < self.start_tick:
            return
        for reading in readings:
            if reading["sensor_id"] == self.target_sensor:
                scale_power_fields(reading, self.multiplier)
