"""Incident responder: translates the investigation's playbook into structured, policy-
gated actions from the fixed allowed set. auto_execute and executed are always False here
- the policy engine (Phase 6) decides auto_execute, and the tool layer sets executed.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from config import settings
from schemas.models import Incident, ResponseAction
from soc.agents.base import AgentCallResult, call_agent
from soc.agents.investigation_agent import InvestigationOutput

SYSTEM_PROMPT = (
    "You are the incident responder for Relay, an AI SOC protecting a smart "
    "electricity grid. Given the incident, the probable attack, and the recommended "
    "playbook, propose containment actions. Each action's type MUST be one of exactly: "
    "QUARANTINE_SENSOR, MARK_DATA_UNTRUSTED, ENABLE_ESTIMATION_FALLBACK, INCREASE_MONITORING, "
    "FREEZE_OPTIMIZATION_INPUT, RECALCULATE_DISPATCH, ISOLATE_SUBSTATION, "
    "CREATE_OPERATOR_APPROVAL, CLOSE_INCIDENT. Never invent a type outside this list. "
    "Respond as JSON matching this schema: {\"actions\": [{\"type\": str, \"target\": str, "
    '"risk": "LOW"|"MEDIUM"|"HIGH"}]}'
)


class ProposedAction(ResponseAction):
    """The LLM's action proposal is structurally barred from setting auto_execute or
    executed - only the policy engine (Phase 6) and the tool layer may set those.
    """

    model_config = ConfigDict(extra="forbid")
    auto_execute: Literal[False] = False
    executed: Literal[False] = False


class ResponseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[ProposedAction]


def _fallback(incident: Incident, playbook: str) -> ResponseOutput:
    actions = [
        ProposedAction(
            type=action_type.strip().upper(),
            target=asset,
            risk=settings.RESPONSE_TOOL_RISK.get(action_type.strip().upper(), "LOW"),
        )
        for action_type in playbook.split(",")
        for asset in incident.affected_assets
    ]
    return ResponseOutput(actions=actions)


def run(incident: Incident, investigation: InvestigationOutput) -> AgentCallResult:
    payload = {
        "incident_id": incident.incident_id,
        "probable_attack": investigation.probable_attack,
        "affected_assets": incident.affected_assets,
        "recommended_playbook": investigation.recommended_playbook,
    }
    return call_agent("response_agent", SYSTEM_PROMPT, payload, ResponseOutput, _fallback(incident, investigation.recommended_playbook))
