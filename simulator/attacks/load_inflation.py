"""Reported demand raised above actual (e.g. actual 50 MW, reported 78 MW). Without
security the optimizer over-generates, raising simulated cost and emissions.
"""

from simulator.attacks.base import ScaledSensorAttack


class LoadInflationAttack(ScaledSensorAttack):
    name = "LOAD_INFLATION"

    def __init__(self, target_sensor: str, start_tick: int, multiplier: float = 1.56):
        super().__init__(target_sensor, start_tick, multiplier)
