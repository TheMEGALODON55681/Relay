"""Threat pattern knowledge base: the attack types Relay recognizes, matched by
the Investigation Agent against incident evidence.
"""

from schemas.models import ThreatPattern

PATTERNS: list[ThreatPattern] = [
    ThreatPattern(
        attack_id="LOAD_INFLATION",
        name="Load Inflation FDI",
        category="False Data Injection",
        indicators=["VOLTAGE_DEVIATION", "LOAD_SPIKE", "GENERATION_LOAD_MISMATCH", "SUBSTATION_AGGREGATION"],
        potential_impact=["unnecessary over-generation", "elevated cost and emissions"],
        recommended_playbook="quarantine_sensor,enable_estimation_fallback,freeze_optimization_input,recalculate_dispatch",
    ),
    ThreatPattern(
        attack_id="LOAD_SUPPRESSION",
        name="Load Suppression FDI",
        category="False Data Injection",
        # No LOAD_SPIKE here: rule_engine._load_spike only fires on a load increase
        # (rejects negative change), so it can never actually be evidence of suppression -
        # listing it caused real load-inflation runs to be misattributed as suppression,
        # since the two patterns otherwise share every remaining indicator.
        indicators=["SUBSTATION_AGGREGATION", "POWER_BALANCE"],
        potential_impact=["under-generation", "insufficient reserve", "unsafe dispatch"],
        recommended_playbook="quarantine_sensor,enable_estimation_fallback,freeze_optimization_input,recalculate_dispatch",
    ),
    ThreatPattern(
        attack_id="COORDINATED_FDI",
        name="Coordinated Stealth FDI",
        category="False Data Injection",
        indicators=["SUBSTATION_AGGREGATION", "POWER_BALANCE", "BATTERY_SOC_CONTINUITY"],
        potential_impact=["substation imbalance", "physical inconsistency", "cross-sensor correlation"],
        recommended_playbook="quarantine_sensor,enable_estimation_fallback,freeze_optimization_input,increase_monitoring,recalculate_dispatch",
    ),
]


def _score(pattern: ThreatPattern, upper: str) -> tuple[int, float]:
    hits = sum(i in upper for i in pattern.indicators)
    return (hits, hits / len(pattern.indicators))


def match(evidence_summary: str) -> ThreatPattern:
    """Scores each pattern by how many of its indicators appear in the evidence and
    returns the best match; defaults to the coordinated pattern (the hardest to
    attribute) when nothing matches. A first-match scan would misattribute patterns
    that share indicators (e.g. SUBSTATION_AGGREGATION appears in more than one).
    Ties on raw hit count break by the fraction of a pattern's own indicators matched,
    so a single shared indicator favors the more specific (fewer-indicator) pattern
    instead of whichever pattern happens to be listed first.
    """
    upper = evidence_summary.upper()
    best = max(PATTERNS, key=lambda p: _score(p, upper))
    return best if _score(best, upper)[0] > 0 else PATTERNS[-1]


def get(attack_id: str) -> ThreatPattern | None:
    return next((p for p in PATTERNS if p.attack_id == attack_id), None)


if __name__ == "__main__":
    # The actual signature a real LOAD_INFLATION run produces (verified against a live
    # dashboard run): LOAD_SPIKE and SUBSTATION_AGGREGATION fire, VOLTAGE_DEVIATION and
    # GENERATION_LOAD_MISMATCH do not (ScaledSensorAttack scales generation and load by
    # the same factor, so their ratio - and the mismatch check - is undisturbed). This
    # must resolve to LOAD_INFLATION, not LOAD_SUPPRESSION, on raw hit count alone.
    assert match("LOAD_SPIKE SUBSTATION_AGGREGATION").attack_id == "LOAD_INFLATION"
    # Single shared indicator with nothing else: LOAD_SUPPRESSION is now the most specific
    # pattern containing it (1/2), ahead of COORDINATED_FDI (1/3) and LOAD_INFLATION (1/4).
    assert match("SUBSTATION_AGGREGATION").attack_id == "LOAD_SUPPRESSION"
    # Unambiguous full match still wins outright.
    assert match("VOLTAGE_DEVIATION LOAD_SPIKE GENERATION_LOAD_MISMATCH SUBSTATION_AGGREGATION").attack_id == "LOAD_INFLATION"
    # No indicators present at all falls back to the hardest-to-attribute pattern.
    assert match("NOTHING_RELEVANT").attack_id == "COORDINATED_FDI"
    print("threat_kb self-check passed")
