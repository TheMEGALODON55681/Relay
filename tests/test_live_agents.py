"""Live LLM path check, deselected by default (see pytest.ini). Run explicitly with
`pytest -m live` to prove the real model still works end to end, not just the
deterministic fallback the default suite exercises.
"""

import pytest

from schemas.models import Incident
from soc.agents import triage_agent
from tests.conftest import BASE_TIME


@pytest.mark.live
def test_triage_agent_reaches_the_real_llm():
    incident = Incident(
        incident_id="live-test",
        status="TRIAGING",
        severity="HIGH",
        created_at=BASE_TIME,
        correlated_alert_ids=["a1"],
        affected_assets=["SUB-1"],
        timeline=[],
        probable_attack=None,
        evidence_package={},
        response_actions=[],
    )
    result = triage_agent.run(incident)
    assert not result.used_fallback, "expected a real LLM response, got the deterministic fallback"
    assert result.output.decision in ("escalate", "close_false_positive")
