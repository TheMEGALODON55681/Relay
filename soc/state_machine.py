"""Deterministic state machine for Incident.status transitions."""

TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"TRIAGING"},
    "TRIAGING": {"INVESTIGATING", "FALSE_POSITIVE"},
    "INVESTIGATING": {"CONTAINMENT_PENDING"},
    "CONTAINMENT_PENDING": {"CONTAINED"},
    "CONTAINED": {"MONITORING"},
    "MONITORING": {"RESOLVED"},
    "RESOLVED": set(),
    "FALSE_POSITIVE": set(),
}


class InvalidTransition(Exception):
    pass


def transition(current: str, target: str) -> str:
    if target not in TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"cannot transition from {current} to {target}")
    return target
