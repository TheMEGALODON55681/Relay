"""Demonstration-only scenario: compromises a sensor with no reconstruction constraint
(a generator) together with one feeder, then broadens to the rest of the feeder group -
so a single run puts all three trust states (TRUSTED, ESTIMATED, QUARANTINED) on screen
at once at onset, then shows the substation's reconstruction collapse as the attack
broadens and its supporting feeders stop being trusted. Not a scored attack: excluded
from evaluation.harness.SCENARIOS and evaluation.ab_compare, it exists to be watched and
screenshotted, not measured (see README Limitations).

Staging the generator and the feeder together, rather than the generator alone first,
is deliberate: attacking the generator first lets its power-balance violation broadcast
(via detection.risk_engine's cross-tick evidence carry-over) to the feeders and
substation before the feeder is even compromised, which quarantines them too early for
the substation to ever reconstruct. Onset together avoids that race.
"""

from simulator.attacks.base import Attack, scale_power_fields
from simulator.grid import FEEDERS, GENERATORS


class EscalatingFdiAttack(Attack):
    name = "ESCALATING_FDI"

    def __init__(self, start_tick: int, broaden_gap: int = 6, multiplier: float = 1.4):
        self.start_tick = start_tick
        self.broaden_gap = broaden_gap
        self.multiplier = multiplier

    def apply(self, readings: list[dict], tick: int) -> None:
        if tick < self.start_tick:
            return
        targets = {GENERATORS[0], FEEDERS[0]}
        if tick - self.start_tick >= self.broaden_gap:
            targets.update(FEEDERS[1:])
        for reading in readings:
            if reading["sensor_id"] in targets:
                scale_power_fields(reading, self.multiplier)
