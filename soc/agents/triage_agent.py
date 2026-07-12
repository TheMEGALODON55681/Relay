"""Tier 1 analyst: interprets detection evidence, correlates concurrent alerts, assigns
severity, and decides to escalate to Tier 2 or close as a false positive.
"""

from typing import Literal

from pydantic import BaseModel, Field

from schemas.models import Incident
from soc.agents.base import AgentCallResult, call_agent

SYSTEM_PROMPT = (
    "You are the Tier 1 triage analyst for Relay, an AI SOC protecting a smart "
    "electricity grid from false-data-injection attacks. Review the detection evidence "
    "for this incident and decide whether it warrants escalation to Tier 2 investigation "
    "or should be closed as a false positive. Respond as JSON matching this schema: "
    '{"assessment": str, "severity": "LOW"|"MEDIUM"|"HIGH"|"CRITICAL", "is_coordinated": bool, '
    '"correlated_alert_ids": [str], "affected_assets": [str], '
    '"decision": "escalate"|"close_false_positive", "confidence": float 0..1, "rationale": str}'
)


class TriageOutput(BaseModel):
    assessment: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    is_coordinated: bool
    correlated_alert_ids: list[str]
    affected_assets: list[str]
    decision: Literal["escalate", "close_false_positive"]
    confidence: float = Field(ge=0, le=1)
    rationale: str


def _fallback(incident: Incident) -> TriageOutput:
    is_coordinated = len(incident.affected_assets) > 1
    severity = incident.severity if incident.severity in ("HIGH", "CRITICAL") else "HIGH" if is_coordinated else "MEDIUM"
    return TriageOutput(
        assessment="Deterministic fallback: escalating based on correlated alert volume and incident severity.",
        severity=severity,
        is_coordinated=is_coordinated,
        correlated_alert_ids=incident.correlated_alert_ids,
        affected_assets=incident.affected_assets,
        decision="escalate",
        confidence=0.5,
        rationale="LLM unavailable or returned invalid output; escalated per fixed policy rather than risk closing a real incident.",
    )


def run(incident: Incident) -> AgentCallResult:
    payload = {
        "incident_id": incident.incident_id,
        "severity": incident.severity,
        "correlated_alert_ids": incident.correlated_alert_ids,
        "affected_assets": incident.affected_assets,
        "evidence_package": incident.evidence_package,
        "timeline": incident.timeline,
    }
    return call_agent("triage_agent", SYSTEM_PROMPT, payload, TriageOutput, _fallback(incident))
