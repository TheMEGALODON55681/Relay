"""Central tunables for Relay. All thresholds are calibratable, not universal truths."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROJECT_NAME = "Relay"

RANDOM_SEED = 42
TICK_SECONDS = 1.0

# --- Unified risk engine: detector weights (must sum to 1.0) ---
RULE_WEIGHT = 0.20
STATISTICAL_WEIGHT = 0.20
ML_WEIGHT = 0.30
PHYSICS_WEIGHT = 0.30

# --- Risk classification bands (inclusive lower bound) ---
RISK_BANDS = [
    (0.00, "NORMAL"),
    (0.30, "OBSERVE"),
    (0.50, "SUSPICIOUS"),
    (0.70, "HIGH_RISK"),
    (0.85, "CRITICAL"),
]
WORKFLOW_TRIGGER_MIN_SCORE = 0.50  # SUSPICIOUS and above

# --- Rule engine thresholds ---
VOLTAGE_NOMINAL = 230.0
VOLTAGE_DEVIATION_PCT = 0.08
FREQUENCY_NOMINAL = 50.0
FREQUENCY_DEVIATION_HZ = 0.3
LOAD_SPIKE_PCT = 0.25
GENERATION_LOAD_MISMATCH_PCT = 0.15
BATTERY_SOC_MAX_STEP_PCT = 0.20
SENSOR_RATE_MAX_STD_MULTIPLE = 5.0
TIMESTAMP_ANOMALY_SECONDS = 5.0

# --- Statistical detector ---
ROLLING_WINDOW_TICKS = 30
EWMA_ALPHA = 0.3
Z_SCORE_THRESHOLD = 3.0

# --- ML detector (Isolation Forest) ---
IFOREST_CONTAMINATION = 0.05
IFOREST_N_ESTIMATORS = 100
IFOREST_TRAIN_SAMPLES = 2000
ML_MODEL_PATH = PROJECT_ROOT / "detection" / "isolation_forest.joblib"

# --- Physics validator tolerances (normalized residual magnitude) ---
POWER_BALANCE_TOLERANCE = 0.08  # generator noise alone gives a natural tail up to ~5%; measured empirically
AGGREGATION_TOLERANCE = 0.02  # substation load equals the feeder sum exactly under normal conditions (no independent noise)
BATTERY_SOC_TOLERANCE = 0.03
ESTIMATED_LOSS_PCT = 0.02
BATTERY_SOC_SENSITIVITY_PCT_PER_MW = 0.05  # shared by the simulator and the physics validator

# --- Incident correlation ---
CORRELATION_WINDOW_SECONDS = 30.0

# --- Policy engine autonomy tiers: classification -> auto-executable action types ---
# Values match ResponseAction.type in schemas/models.py exactly.
AUTONOMY_TIERS = {
    "NORMAL": [],
    "OBSERVE": [],
    "SUSPICIOUS": ["INCREASE_MONITORING", "MARK_DATA_UNTRUSTED"],
    "HIGH_RISK": [
        "QUARANTINE_SENSOR",
        "ENABLE_ESTIMATION_FALLBACK",
        "FREEZE_OPTIMIZATION_INPUT",
    ],
    "CRITICAL": [
        "QUARANTINE_SENSOR",
        "ENABLE_ESTIMATION_FALLBACK",
        "FREEZE_OPTIMIZATION_INPUT",
        "RECALCULATE_DISPATCH",
    ],
}
# Never auto-executed regardless of tier; always requires operator approval.
APPROVAL_ONLY_ACTIONS = {"ISOLATE_SUBSTATION"}

# Fixed risk level per response tool (PRD Section 8). Every tool is LOW except
# isolate_substation, which is HIGH and therefore always approval-only (see above).
RESPONSE_TOOL_RISK = {
    "QUARANTINE_SENSOR": "LOW",
    "MARK_DATA_UNTRUSTED": "LOW",
    "ENABLE_ESTIMATION_FALLBACK": "LOW",
    "INCREASE_MONITORING": "LOW",
    "FREEZE_OPTIMIZATION_INPUT": "LOW",
    "RECALCULATE_DISPATCH": "LOW",
    "ISOLATE_SUBSTATION": "HIGH",
    "CREATE_OPERATOR_APPROVAL": "LOW",
    "CLOSE_INCIDENT": "LOW",
}

# --- Agent / LLM ---
LLM_MODEL = os.getenv("LLM_MODEL", "groq/openai/gpt-oss-120b")
AGENT_MAX_RETRIES = 1

# --- Storage ---
DB_PATH = "relay.db"

# --- Evaluation harness ---
EVAL_RUNS_PER_SCENARIO = 30
RESULTS_DIR = "results"

# --- Optimizer stub ---
GENERATION_COST_PER_MWH = 60.0
GENERATION_EMISSIONS_PER_MWH = 0.4  # tons CO2 per MWh
