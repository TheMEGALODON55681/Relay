"""Several feeders shifted by small, individually plausible amounts (e.g. +8%, +7%, +9%,
-4%). Individually each looks acceptable; together they create substation imbalance and
physical inconsistency. The advanced demonstration: must be caught primarily by the
physics and ML layers, not the rule or statistical layers.
"""

from simulator.attacks.base import Attack, scale_power_fields
from simulator.grid import FEEDERS

DEFAULT_SHIFTS = {FEEDERS[0]: 1.08, FEEDERS[1]: 1.07, FEEDERS[2]: 1.09, FEEDERS[3]: 0.96}


class CoordinatedFdiAttack(Attack):
    name = "COORDINATED_FDI"

    def __init__(self, start_tick: int, shifts: dict[str, float] | None = None):
        self.start_tick = start_tick
        self.shifts = DEFAULT_SHIFTS if shifts is None else shifts

    def apply(self, readings: list[dict], tick: int) -> None:
        if tick < self.start_tick:
            return
        for reading in readings:
            multiplier = self.shifts.get(reading["sensor_id"])
            if multiplier is not None:
                scale_power_fields(reading, multiplier)
