"""Policy engine: classification -> autonomy tier -> which proposed actions may
auto-execute. The LLM never sets auto_execute; this is the only place that does.
"""

import uuid

from soc import policy_engine
from soc.incident_manager import IncidentManager
from schemas.models import DetectionResult, ResponseAction


def _incident(classification: str, db_path: str):
    manager = IncidentManager(db_path=db_path)
    detection = DetectionResult(
        event_id=str(uuid.uuid4()),
        sensor_id="FEEDER-1",
        rule_score=0.5,
        statistical_score=0.5,
        ml_score=0.5,
        physics_score=0.5,
        risk_score=0.5,
        classification=classification,
        evidence={},
        trigger_soc_workflow=True,
    )
    incident = manager.handle_detection("FEEDER-1", "FEEDER-1", detection)
    manager.close()
    return incident


def _action(action_type: str) -> ResponseAction:
    return ResponseAction(type=action_type, target="FEEDER-1", risk="LOW", auto_execute=False, executed=False)


def test_suspicious_auto_executes_only_low_risk_monitoring(tmp_path):
    incident = _incident("SUSPICIOUS", str(tmp_path / "a.db"))
    actions = [_action("INCREASE_MONITORING"), _action("QUARANTINE_SENSOR")]
    policy_engine.apply(incident, actions)
    assert actions[0].auto_execute is True
    assert actions[1].auto_execute is False


def test_high_risk_auto_executes_temporary_containment(tmp_path):
    incident = _incident("HIGH_RISK", str(tmp_path / "b.db"))
    actions = [_action("QUARANTINE_SENSOR"), _action("ENABLE_ESTIMATION_FALLBACK"), _action("FREEZE_OPTIMIZATION_INPUT")]
    policy_engine.apply(incident, actions)
    assert all(a.auto_execute for a in actions)


def test_isolate_substation_is_never_auto_executed_even_at_critical(tmp_path):
    incident = _incident("CRITICAL", str(tmp_path / "c.db"))
    actions = [_action("ISOLATE_SUBSTATION"), _action("RECALCULATE_DISPATCH")]
    policy_engine.apply(incident, actions)
    assert actions[0].auto_execute is False
    assert actions[1].auto_execute is True


def test_isolate_substation_held_for_approval_at_high_risk(tmp_path):
    """PRD Section 8: a high-risk incident auto-contains but holds substation isolation
    for approval - the exact scenario in the Phase 6 acceptance criteria.
    """
    incident = _incident("HIGH_RISK", str(tmp_path / "e.db"))
    actions = [_action("QUARANTINE_SENSOR"), _action("ISOLATE_SUBSTATION")]
    policy_engine.apply(incident, actions)
    assert actions[0].auto_execute is True
    assert actions[1].auto_execute is False


def test_normal_classification_auto_executes_nothing(tmp_path):
    incident = _incident("NORMAL", str(tmp_path / "d.db"))
    actions = [_action("INCREASE_MONITORING")]
    policy_engine.apply(incident, actions)
    assert actions[0].auto_execute is False
