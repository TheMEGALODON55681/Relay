"""Runs Triage for every incident, then runs Investigation -> Response -> Analyst only
when Triage escalates (a false positive stops after Triage - see
PROJECT_PLAN.md's attack-vs-fault principle). Response actions are policy-gated and
auto-approved ones are executed against the gateway before Analyst summarizes.
Stores an AgentDecision for every agent execution.

Runs the full Triage->Analyst pipeline at most once per incident: a later alert can
correlate into an incident that's already TRIAGING or further along (see
soc/incident_manager.py's correlation window), and that only needs to enrich the
incident's evidence, not restart the SOC workflow. If the incident is already at
CONTAINMENT_PENDING, a correlated alert can still raise its classification (e.g.
SUSPICIOUS -> HIGH_RISK) or bring in a new affected asset the original proposal never
covered (e.g. a false positive on one sensor correlates with a real attack on another).
Policy is re-applied to the full action set - extended to cover any new asset with the
same action types already decided - and any newly-unlocked action executes, without
re-running the agents.
"""

from datetime import datetime

from config import settings
from gateway.trusted_data_gateway import TrustedDataGateway
from schemas.models import AgentDecision, Incident, ResponseAction
from soc import policy_engine
from soc.agents import analyst_agent, investigation_agent, response_agent, triage_agent
from soc.agents.base import AgentCallResult
from soc.incident_manager import IncidentManager
from soc.tools import response_tools


def _record(agent_name: str, incident: Incident, result: AgentCallResult) -> AgentDecision:
    return AgentDecision(
        agent=agent_name,
        incident_id=incident.incident_id,
        input_summary={"incident_id": incident.incident_id, "status": incident.status},
        output=result.output.model_dump(),
        confidence=result.confidence,
        duration_ms=result.duration_ms,
        timestamp=datetime.now(),
    )


def _propose_for_new_assets(incident: Incident) -> list[ResponseAction]:
    """A correlated alert can add an asset to incident.affected_assets after the
    original proposal. Extends coverage to it using the same action types already
    decided for this incident, rather than re-invoking the Response Agent.
    """
    types = {a.type for a in incident.response_actions}
    covered = {(a.type, a.target) for a in incident.response_actions}
    return [
        ResponseAction(type=t, target=asset, risk=settings.RESPONSE_TOOL_RISK.get(t, "LOW"), auto_execute=False, executed=False)
        for asset in incident.affected_assets
        for t in types
        if (t, asset) not in covered
    ]


def _reapply_policy_for_correlation(incident: Incident, manager: IncidentManager, gateway: TrustedDataGateway) -> None:
    incident.response_actions += _propose_for_new_assets(incident)
    actions = policy_engine.apply(incident, incident.response_actions)
    response_tools.execute_all(gateway, actions)
    manager.save(incident)


def run_incident(incident: Incident, manager: IncidentManager, gateway: TrustedDataGateway) -> list[AgentDecision]:
    if incident.status == "CONTAINMENT_PENDING":
        _reapply_policy_for_correlation(incident, manager, gateway)
        return []
    if incident.status != "NEW":
        return []

    decisions = []

    incident = manager.advance(incident, "TRIAGING")
    triage = triage_agent.run(incident)
    decisions.append(_record("triage_agent", incident, triage))
    if triage.output.decision == "close_false_positive":
        manager.advance(incident, "FALSE_POSITIVE", note=triage.output.rationale)
        return decisions

    incident = manager.advance(incident, "INVESTIGATING")
    investigation = investigation_agent.run(incident)
    decisions.append(_record("investigation_agent", incident, investigation))
    incident.probable_attack = investigation.output.probable_attack
    manager.save(incident)

    incident = manager.advance(incident, "CONTAINMENT_PENDING")
    response = response_agent.run(incident, investigation.output)
    decisions.append(_record("response_agent", incident, response))
    actions = policy_engine.apply(incident, response.output.actions)
    response_tools.execute_all(gateway, actions)
    incident.response_actions = actions
    manager.save(incident)

    analyst = analyst_agent.run(incident)
    decisions.append(_record("analyst_agent", incident, analyst))

    return decisions
