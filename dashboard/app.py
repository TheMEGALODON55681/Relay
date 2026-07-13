"""Streamlit SOC dashboard entry point (PRD Section 10). Owns page setup, the sidebar
scenario controls, and driving one live run; the panels themselves render from
dashboard/panels.py, and the tick-by-tick simulation lives in dashboard/live_run.py.
"""

import json
import sys
from pathlib import Path

# `streamlit run` puts this file's own directory on sys.path, not the repo root -
# needed so the project's usual absolute imports (`from config import settings`) resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from config import settings  # noqa: E402
from dashboard import panels, theme  # noqa: E402
from dashboard.live_run import run_live  # noqa: E402
from evaluation.harness import ESCALATING_FDI_DEMO_SEED, ESCALATING_FDI_SNAPSHOT_TICK, SCENARIOS  # noqa: E402

st.set_page_config(page_title=f"{settings.PROJECT_NAME} SOC", layout="wide")
theme.inject()

# Demonstration-only, on top of the scored scenarios - never fed into evaluation.harness
# or ab_compare (see simulator/attacks/escalating_fdi.py).
_DASHBOARD_SCENARIOS = (*SCENARIOS, "ESCALATING_FDI (demo)")


@st.cache_data
def _load_aggregate() -> dict | None:
    path = Path(settings.RESULTS_DIR) / "metrics.json"
    return json.loads(path.read_text()) if path.exists() else None


def _sidebar() -> None:
    st.sidebar.header("Scenario")
    choice = st.sidebar.selectbox("Attack", _DASHBOARD_SCENARIOS)
    is_demo = choice.endswith("(demo)")
    scenario = "ESCALATING_FDI" if is_demo else choice
    default_seed = ESCALATING_FDI_DEMO_SEED if is_demo else settings.RANDOM_SEED
    seed = st.sidebar.number_input("Random seed", value=default_seed, step=1)
    if is_demo:
        st.sidebar.caption(
            f"Demonstration only, excluded from every evaluation metric. Compromises an "
            f"unconstrained generator and a reconstructable feeder together, then broadens "
            f"to the whole feeder group - seed {ESCALATING_FDI_DEMO_SEED} shows Gateway "
            f"State holding all three trust states at once at onset, then losing the "
            f"ability to estimate as the attack broadens."
        )
    if st.sidebar.button("Run scenario", type="primary", use_container_width=True):
        snapshot_tick = ESCALATING_FDI_SNAPSHOT_TICK if is_demo else None
        with st.spinner(f"Simulating {scenario}, security ON and OFF..."):
            st.session_state["trace_on"] = run_live(scenario, security_enabled=True, seed=int(seed), snapshot_tick=snapshot_tick)
            st.session_state["trace_off"] = run_live(scenario, security_enabled=False, seed=int(seed), snapshot_tick=snapshot_tick)
    st.sidebar.caption(
        "Each run drives the same simulated attack twice with an identical seed: once with "
        "the SOC enabled, once without, so the Counterfactual panel can show the delta."
    )


st.title(settings.PROJECT_NAME)
st.caption("Agentic AI SOC for a simulated smart grid: detects false-data-injection attacks and keeps poisoned telemetry out of dispatch.")
_sidebar()

if "trace_on" not in st.session_state:
    st.info("Pick a scenario in the sidebar and click **Run scenario** to simulate an attack and watch the SOC respond.")
    st.stop()

on, off = st.session_state["trace_on"], st.session_state["trace_off"]
aggregate = _load_aggregate()
panels.render_status_bar(on)

tabs = st.tabs(["Security Overview", "Gateway State", "Live Agent Activity", "Incident Investigation", "Detection Analytics", "Counterfactual"])
with tabs[0]:
    panels.render_security_overview(on, aggregate)
with tabs[1]:
    panels.render_gateway_state(on)
with tabs[2]:
    panels.render_agent_activity(on)
with tabs[3]:
    panels.render_incident_investigation(on)
with tabs[4]:
    panels.render_detection_analytics(on, aggregate)
with tabs[5]:
    panels.render_counterfactual(on, off)
