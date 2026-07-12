"""Deterministic policy engine: maps an incident's detection classification to an
autonomy tier and decides which proposed response actions may auto-execute versus
require operator approval. The LLM never sets auto_execute - this is the only place
that does.
"""

from config import settings
from schemas.models import Incident, ResponseAction

_CLASSIFICATION_ORDER = [band for _, band in settings.RISK_BANDS]


def _incident_classification(incident: Incident) -> str:
    """Highest classification among the incident's correlated alerts."""
    classifications = [entry["detection"]["classification"] for entry in incident.evidence_package.values()]
    return max(classifications, key=_CLASSIFICATION_ORDER.index, default="NORMAL")


def apply(incident: Incident, actions: list[ResponseAction]) -> list[ResponseAction]:
    """Sets auto_execute on each action per the autonomy tier for the incident's
    classification. Actions in APPROVAL_ONLY_ACTIONS never auto-execute regardless of tier.
    """
    auto_allowed = set(settings.AUTONOMY_TIERS.get(_incident_classification(incident), []))
    for action in actions:
        action.auto_execute = action.type in auto_allowed and action.type not in settings.APPROVAL_ONLY_ACTIONS
    return actions
