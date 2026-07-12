"""Tier 2 analyst: gathers deeper evidence, matches the incident against the threat
knowledge base, names the probable attack, and selects a playbook.
"""

from pydantic import BaseModel, Field, model_validator

from schemas.models import Incident
from soc import threat_kb
from soc.agents.base import AgentCallResult, call_agent

SYSTEM_PROMPT = (
    "You are the Tier 2 investigation analyst for Relay, an AI SOC protecting a "
    "smart electricity grid from false-data-injection attacks. Given the incident's "
    "evidence package and the threat knowledge base of known attack patterns, name the "
    "probable attack, cite the attack_id it matches from the knowledge base, list which "
    "indicators matched, and recommend a playbook. Respond as JSON matching this schema: "
    '{"probable_attack": str, "attack_id": str, "matched_indicators": [str], '
    '"possible_attack_paths": [str], "confidence": float 0..1, "recommended_playbook": str}'
)


class InvestigationOutput(BaseModel):
    probable_attack: str
    attack_id: str
    matched_indicators: list[str]
    possible_attack_paths: list[str]
    confidence: float = Field(ge=0, le=1)
    recommended_playbook: str

    @model_validator(mode="after")
    def _matches_threat_kb(self) -> "InvestigationOutput":
        """The system recognizes exactly the 3 attack patterns in the KB (Section 6) -
        an attack_id, name, or playbook outside that set is invalid output, not a novel
        finding, so it goes through the same retry-then-fallback path as bad JSON.
        """
        pattern = threat_kb.get(self.attack_id)
        if not pattern or (self.probable_attack, self.recommended_playbook) != (pattern.name, pattern.recommended_playbook):
            raise ValueError(f"attack_id {self.attack_id!r} does not match a known threat KB pattern")
        return self


def _evidence_summary(incident: Incident) -> str:
    keys = set()
    for entry in incident.evidence_package.values():
        evidence = entry.get("detection", {}).get("evidence", {})
        for detector_evidence in evidence.values():
            keys.update(detector_evidence.keys())
    return " ".join(keys)


def _fallback(incident: Incident) -> InvestigationOutput:
    summary = _evidence_summary(incident)
    pattern = threat_kb.match(summary)
    upper = summary.upper()
    return InvestigationOutput(
        probable_attack=pattern.name,
        attack_id=pattern.attack_id,
        matched_indicators=[i for i in pattern.indicators if i in upper],
        possible_attack_paths=pattern.potential_impact,
        confidence=0.5,
        recommended_playbook=pattern.recommended_playbook,
    )


def run(incident: Incident) -> AgentCallResult:
    payload = {
        "incident_id": incident.incident_id,
        "timeline": incident.timeline,
        "evidence_package": incident.evidence_package,
        "threat_kb": [p.model_dump() for p in threat_kb.PATTERNS],
    }
    return call_agent("investigation_agent", SYSTEM_PROMPT, payload, InvestigationOutput, _fallback(incident))
