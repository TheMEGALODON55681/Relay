"""Simplified digital twin: generators, one substation, feeders, and a battery.

Not a physics-accurate power-systems model. Realistic enough that the physical
consistency checks in the detection engine (Phase 2) are meaningful.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from config.settings import BATTERY_SOC_SENSITIVITY_PCT_PER_MW, ESTIMATED_LOSS_PCT, RANDOM_SEED

GENERATORS = ["GEN-1", "GEN-2"]
FEEDERS = ["FEEDER-1", "FEEDER-2", "FEEDER-3", "FEEDER-4"]
SUBSTATION = "SUB-1"
BATTERY = "BATT-1"

SENSOR_KIND = {
    **{g: "GENERATOR" for g in GENERATORS},
    **{f: "FEEDER" for f in FEEDERS},
    SUBSTATION: "SUBSTATION",
    BATTERY: "BATTERY",
}


@dataclass(frozen=True)
class Constraint:
    """A physical relationship the gateway can solve for exactly one unknown member,
    given every other member's latest trusted reading. See
    gateway.trusted_data_gateway for the observability rule this supports: one
    equation solves for one unknown, two or more unknowns is unobservable.
    """

    name: str
    members: tuple[str, ...]
    solve: Callable[[str, dict[str, float]], float]


def _solve_substation_aggregation(target: str, known: dict[str, float]) -> float:
    """sub = sum(feeders), the same relationship detection.physics_validator's
    SUBSTATION_AGGREGATION check verifies. known holds every constraint member
    except target, keyed by sensor_id.
    """
    if target == SUBSTATION:
        return sum(known[f] for f in FEEDERS)
    return known[SUBSTATION] - sum(v for sensor_id, v in known.items() if sensor_id != SUBSTATION)


# One constraint today. A second one (e.g. a power-balance reconstruction across
# generators and the battery) can be added by appending another Constraint here;
# gateway.trusted_data_gateway consumes this list generically.
CONSTRAINTS: list[Constraint] = [
    Constraint(name="SUBSTATION_AGGREGATION", members=(SUBSTATION, *FEEDERS), solve=_solve_substation_aggregation),
]

CONSTRAINTS_BY_SENSOR: dict[str, list[Constraint]] = defaultdict(list)
for _constraint in CONSTRAINTS:
    for _member in _constraint.members:
        CONSTRAINTS_BY_SENSOR[_member].append(_constraint)

NOMINAL_VOLTAGE = 230.0
NOMINAL_FREQUENCY = 50.0
BASE_FEEDER_LOAD_MW = 12.5


@dataclass
class SensorReading:
    sensor_id: str
    asset_id: str
    voltage: float
    current: float
    frequency: float
    active_power: float
    reactive_power: float
    power_factor: float
    load: float
    generation: float
    battery_soc: float


class Grid:
    """Advances one simulated tick at a time and returns raw per-sensor readings."""

    def __init__(self, seed: int = RANDOM_SEED) -> None:
        self._rng = np.random.default_rng(seed)
        self.battery_soc = 50.0

    def step(self) -> list[SensorReading]:
        feeder_loads = {f: max(0.0, BASE_FEEDER_LOAD_MW + self._rng.normal(0, 0.6)) for f in FEEDERS}
        total_load = sum(feeder_loads.values())

        battery_flow = self._rng.normal(0, 0.5)  # positive = discharging into grid
        soc_delta = battery_flow * BATTERY_SOC_SENSITIVITY_PCT_PER_MW
        self.battery_soc = float(np.clip(self.battery_soc - soc_delta, 5.0, 95.0))

        required_generation = total_load * (1 + ESTIMATED_LOSS_PCT) - battery_flow
        gen_split = required_generation / len(GENERATORS)
        generator_outputs = {g: max(0.0, gen_split + self._rng.normal(0, 0.4)) for g in GENERATORS}
        total_generation = sum(generator_outputs.values())

        readings = [self._reading(g, g, generator_outputs[g], load=0.0, generation=generator_outputs[g]) for g in GENERATORS]
        readings += [self._reading(f, f, feeder_loads[f], load=feeder_loads[f], generation=0.0) for f in FEEDERS]
        readings.append(self._reading(SUBSTATION, SUBSTATION, total_generation, load=total_load, generation=total_generation))
        readings.append(self._reading(BATTERY, BATTERY, battery_flow, load=0.0, generation=0.0))
        return readings

    def _reading(self, sensor_id: str, asset_id: str, active_power: float, load: float, generation: float) -> SensorReading:
        voltage = NOMINAL_VOLTAGE + self._rng.normal(0, 0.8)
        frequency = NOMINAL_FREQUENCY + self._rng.normal(0, 0.02)
        power_factor = float(np.clip(0.95 + self._rng.normal(0, 0.01), 0.85, 1.0))
        reactive_power = active_power * np.tan(np.arccos(power_factor))
        current = abs(active_power) * 1000 / (voltage * power_factor)
        return SensorReading(
            sensor_id=sensor_id,
            asset_id=asset_id,
            voltage=round(voltage, 2),
            current=round(current, 2),
            frequency=round(frequency, 3),
            active_power=round(active_power, 3),
            reactive_power=round(reactive_power, 3),
            power_factor=round(power_factor, 4),
            load=round(load, 3),
            generation=round(generation, 3),
            battery_soc=round(self.battery_soc, 2),
        )
