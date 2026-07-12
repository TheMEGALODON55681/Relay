"""Reported demand lowered below actual (e.g. actual 90 MW, reported 55 MW). Simulated
impact is under-generation, insufficient reserve, and unsafe dispatch.
"""

from simulator.attacks.base import ScaledSensorAttack


class LoadSuppressionAttack(ScaledSensorAttack):
    name = "LOAD_SUPPRESSION"

    def __init__(self, target_sensor: str, start_tick: int, multiplier: float = 0.61):
        super().__init__(target_sensor, start_tick, multiplier)
