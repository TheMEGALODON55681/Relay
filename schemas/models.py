"""Pydantic v2 data contracts. Every boundary in the system exchanges these types."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class SensorState(str, Enum):
    TRUSTED = "TRUSTED"
    ESTIMATED = "ESTIMATED"
    QUARANTINED = "QUARANTINED"


class EstimationResult(BaseModel):
    success: bool
    state: SensorState
    estimate: float | None
    confidence: float | None
    reason: str


class TelemetryEvent(BaseModel):
    sensor_id: str
    asset_id: str
    timestamp: datetime
    voltage: float
    current: float
    frequency: float
    active_power: float
    reactive_power: float
    power_factor: float
    load: float
    generation: float
    battery_soc: float
    is_attacked: bool  # ground truth from simulator, for evaluation only; never read by detection


class DetectionResult(BaseModel):
    event_id: str
    sensor_id: str
    rule_score: float
    statistical_score: float
    ml_score: float
    physics_score: float
    risk_score: float
    classification: Literal["NORMAL", "OBSERVE", "SUSPICIOUS", "HIGH_RISK", "CRITICAL"]
    evidence: dict
    trigger_soc_workflow: bool


class Alert(BaseModel):
    alert_id: str
    event_id: str
    sensor_id: str
    asset_id: str
    severity: str
    classification: str
    created_at: datetime
    detection: DetectionResult


class ResponseAction(BaseModel):
    type: Literal[
        "QUARANTINE_SENSOR",
        "MARK_DATA_UNTRUSTED",
        "ENABLE_ESTIMATION_FALLBACK",
        "INCREASE_MONITORING",
        "FREEZE_OPTIMIZATION_INPUT",
        "RECALCULATE_DISPATCH",
        "ISOLATE_SUBSTATION",
        "CREATE_OPERATOR_APPROVAL",
        "CLOSE_INCIDENT",
    ]
    target: str
    risk: Literal["LOW", "MEDIUM", "HIGH"]
    auto_execute: bool  # set by the policy engine, never by the LLM
    executed: bool


class Incident(BaseModel):
    incident_id: str
    status: Literal[
        "NEW",
        "TRIAGING",
        "INVESTIGATING",
        "CONTAINMENT_PENDING",
        "CONTAINED",
        "MONITORING",
        "RESOLVED",
        "FALSE_POSITIVE",
    ]
    severity: str
    created_at: datetime
    correlated_alert_ids: list[str]
    affected_assets: list[str]
    timeline: list[dict]  # every state change and agent action, with timestamp
    probable_attack: str | None
    evidence_package: dict
    response_actions: list[ResponseAction]


class AgentDecision(BaseModel):
    agent: str
    incident_id: str
    input_summary: dict
    output: dict  # the validated structured output
    confidence: float
    duration_ms: int
    timestamp: datetime


class ThreatPattern(BaseModel):
    attack_id: str
    name: str
    category: str
    indicators: list[str]
    potential_impact: list[str]
    recommended_playbook: str


class EvaluationRun(BaseModel):
    scenario: str
    run_index: int
    security_enabled: bool
    attack_detected: bool
    detection_latency_ticks: int | None
    containment_latency_ticks: int | None
    dispatch_cost: float
    dispatch_emissions: float
    unnecessary_generation_mwh: float
    false_positive: bool
