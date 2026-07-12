"""Minimal dispatch stub: allocate generation to meet demand and report cost/emissions.

Intentionally simple. Its purpose is to make the cost of acting on poisoned versus
verified data measurable, not to model real dispatch optimization.
"""

from config import settings

TICK_HOURS = settings.TICK_SECONDS / 3600


def dispatch(load_mw: float) -> dict:
    energy_mwh = load_mw * TICK_HOURS
    cost = energy_mwh * settings.GENERATION_COST_PER_MWH
    emissions = energy_mwh * settings.GENERATION_EMISSIONS_PER_MWH
    return {
        "generation_mw": round(load_mw, 3),
        "energy_mwh": round(energy_mwh, 6),
        "cost": round(cost, 4),
        "emissions": round(emissions, 5),
    }
