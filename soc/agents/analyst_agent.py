"""Reporting and explainability: produces executive and technical summaries and answers
operator questions in natural language, given the full incident record.
"""

from pydantic import BaseModel, Field

from schemas.models import Incident
from soc.agents.base import AgentCallResult, call_agent

SYSTEM_PROMPT = (
    "You are the reporting analyst for Relay, an AI SOC protecting a smart "
    "electricity grid. Given the full incident record - detection evidence, agent "
    "decisions, and response actions - write an executive summary for a non-technical "
    "reader, a technical summary for an operator, and answer the operator's standard "
    "questions. Respond as JSON matching this schema: "
    '{"executive_summary": str, "technical_summary": str, '
    '"impact_prevented": {"unnecessary_generation_mwh": float, "cost_delta": float, "emissions_delta": float}, '
    '"operator_answers": {"why_critical": str, "evidence": str, "what_without_containment": str, '
    '"sensors_quarantined": [str], "detection_confidence": float 0..1}}'
)


class ImpactPrevented(BaseModel):
    unnecessary_generation_mwh: float
    cost_delta: float
    emissions_delta: float


class OperatorAnswers(BaseModel):
    why_critical: str
    evidence: str
    what_without_containment: str
    sensors_quarantined: list[str]
    detection_confidence: float = Field(ge=0, le=1)


class AnalystOutput(BaseModel):
    executive_summary: str
    technical_summary: str
    impact_prevented: ImpactPrevented
    operator_answers: OperatorAnswers


def _fallback(incident: Incident) -> AnalystOutput:
    quarantined = [a.target for a in incident.response_actions if a.type == "QUARANTINE_SENSOR"]
    return AnalystOutput(
        executive_summary=(
            f"Relay detected and contained a {incident.severity.lower()}-severity incident "
            f"({incident.probable_attack or 'unclassified attack'}) affecting {len(incident.affected_assets)} sensor(s)."
        ),
        technical_summary=(
            f"Incident {incident.incident_id}: {len(incident.correlated_alert_ids)} correlated alerts, "
            f"probable attack {incident.probable_attack or 'unknown'}, {len(incident.response_actions)} response action(s) proposed."
        ),
        impact_prevented=ImpactPrevented(unnecessary_generation_mwh=0.0, cost_delta=0.0, emissions_delta=0.0),
        operator_answers=OperatorAnswers(
            why_critical=f"Severity {incident.severity} with {len(incident.affected_assets)} affected assets.",
            evidence="See incident.evidence_package for per-alert detection scores.",
            what_without_containment="Poisoned telemetry would have reached the optimizer unfiltered.",
            sensors_quarantined=quarantined,
            detection_confidence=0.5,
        ),
    )


def run(incident: Incident) -> AgentCallResult:
    payload = {
        "incident_id": incident.incident_id,
        "severity": incident.severity,
        "probable_attack": incident.probable_attack,
        "affected_assets": incident.affected_assets,
        "response_actions": [a.model_dump() for a in incident.response_actions],
        "evidence_package": incident.evidence_package,
    }
    return call_agent("analyst_agent", SYSTEM_PROMPT, payload, AnalystOutput, _fallback(incident))
