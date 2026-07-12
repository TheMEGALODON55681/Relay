"""Unified risk engine: weighted aggregation and classification band assignment."""

from detection import ml_detector, physics_validator, risk_engine, rule_engine, statistical_detector
from simulator.grid import SUBSTATION
from tests.conftest import make_event


def _stub_detectors(monkeypatch, score: float):
    monkeypatch.setattr(rule_engine, "evaluate", lambda ctx: (score, {"rule": score}))
    monkeypatch.setattr(statistical_detector, "evaluate", lambda ctx: (score, {"stat": score}))
    monkeypatch.setattr(ml_detector, "evaluate", lambda ctx: (score, {"ml": score}))
    monkeypatch.setattr(physics_validator, "evaluate", lambda ctx: (score, {"physics": score}))


# physics evidence is only ever fresh on a substation/battery event (see risk_engine.py's
# _PHYSICS_SOURCE_ASSETS); use a substation event so the stubbed physics score is not
# silently skipped in favor of the (empty) last-tick cache.
def test_all_max_scores_classify_critical(monkeypatch):
    _stub_detectors(monkeypatch, 1.0)
    result = risk_engine.RiskEngine().evaluate(make_event(sensor_id=SUBSTATION))
    assert result.risk_score == 1.0
    assert result.classification == "CRITICAL"
    assert result.trigger_soc_workflow is True


def test_all_zero_scores_classify_normal(monkeypatch):
    _stub_detectors(monkeypatch, 0.0)
    result = risk_engine.RiskEngine().evaluate(make_event())
    assert result.risk_score == 0.0
    assert result.classification == "NORMAL"
    assert result.trigger_soc_workflow is False


def test_workflow_trigger_boundary(monkeypatch):
    _stub_detectors(monkeypatch, 0.5)
    result = risk_engine.RiskEngine().evaluate(make_event(sensor_id=SUBSTATION))
    assert result.risk_score == 0.5
    assert result.classification == "SUSPICIOUS"
    assert result.trigger_soc_workflow is True


def test_evidence_contains_all_four_detector_keys(monkeypatch):
    _stub_detectors(monkeypatch, 0.0)
    result = risk_engine.RiskEngine().evaluate(make_event())
    assert set(result.evidence.keys()) == {"rule", "statistical", "ml", "physics"}
