"""Renders the five SOC dashboard panels (PRD Section 10). Each function takes the data
it needs (a RunTrace, and/or the loaded evaluation harness aggregate) and draws directly
into the current Streamlit container - kept separate from dashboard/app.py, which only
owns page setup, the sidebar, and driving a live run.
"""

import pandas as pd
import streamlit as st

from config import settings
from dashboard.live_run import RunTrace
from evaluation.harness import ATTACK_START_TICK, TICKS_PER_RUN
from simulator.grid import SUBSTATION

_CLASSIFICATION_COLOR = {"NORMAL": "#64748B", "OBSERVE": "#3B82F6", "SUSPICIOUS": "#D97706", "HIGH_RISK": "#EA580C", "CRITICAL": "#DC2626"}
_STATUS_COLOR = {"TRUSTED": "#16A34A", "ESTIMATED": "#D97706", "QUARANTINED": "#DC2626"}
_ACTIVE_STATUSES = {"NEW", "TRIAGING", "INVESTIGATING", "CONTAINMENT_PENDING", "CONTAINED", "MONITORING"}
_SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
_MINUTES_PER_RUN = TICKS_PER_RUN * settings.TICK_SECONDS / 60


def _badge(label: str, color: str) -> str:
    return f'<span style="background:{color}22;color:{color};border:1px solid {color}66;border-radius:4px;padding:2px 8px;font-size:0.85em;font-weight:600;">{label}</span>'


def render_security_overview(on: RunTrace, aggregate: dict | None) -> None:
    active = [i for i in on.incidents if i.status in _ACTIVE_STATUSES]
    critical = [i for i in active if i.severity == "CRITICAL"]
    alerts = sum(len(i.correlated_alert_ids) for i in on.incidents)
    confidences = [d.confidence for d in on.decisions]
    quarantined = [s for s, status in on.gateway_status.items() if status != "TRUSTED"]
    threat_level = max((i.severity for i in on.incidents), default="NONE", key=lambda s: _SEVERITY_ORDER.index(s))

    cols = st.columns(4)
    cols[0].metric("Threat level", threat_level)
    cols[1].metric("Active incidents", len(active))
    cols[2].metric("Critical incidents", len(critical))
    cols[3].metric("Alerts / min (simulated)", f"{alerts / _MINUTES_PER_RUN:.1f}")
    cols = st.columns(4)
    cols[0].metric("Mean detection confidence", f"{sum(confidences) / len(confidences):.0%}" if confidences else "-")
    cols[1].metric("Sensors quarantined", f"{len(quarantined)} / {len(on.gateway_status)}")
    det = (aggregate or {}).get("detection", {})
    cols[2].metric("Mean detection latency (ticks)", det.get("mean_detection_latency_ticks", "-"))
    cols[3].metric("Mean containment latency (ticks)", det.get("mean_containment_latency_ticks", "-"))
    if aggregate is None:
        st.caption("Latency figures need a harness run: `python -m evaluation.harness`.")
    else:
        st.caption("Latency figures are aggregate means from the last evaluation harness run, not this single live run.")


_AGENT_SUMMARY = {
    "triage_agent": lambda o: f"{o.get('decision')} - {o.get('rationale', '')[:120]}",
    "investigation_agent": lambda o: f"probable attack: {o.get('probable_attack')} ({', '.join(o.get('matched_indicators', []))})",
    "response_agent": lambda o: f"{len(o.get('actions', []))} action(s) proposed",
    "analyst_agent": lambda o: o.get("executive_summary", "")[:160],
}


def render_agent_activity(on: RunTrace) -> None:
    if not on.decisions:
        st.info("No incident escalated during this run - nothing for the agents to act on.")
        return
    for decision in sorted(on.decisions, key=lambda d: d.timestamp):
        summarize = _AGENT_SUMMARY.get(decision.agent, lambda o: str(o))
        with st.container(border=True):
            top = st.columns([2, 5, 1])
            top[0].markdown(_badge(decision.agent.replace("_", " ").title(), "#3B82F6"), unsafe_allow_html=True)
            top[1].write(summarize(decision.output))
            top[2].caption(f"{decision.duration_ms} ms")
            with st.expander("Raw output"):
                st.json(decision.output)


def render_incident_investigation(on: RunTrace) -> None:
    if not on.incidents:
        st.info("No incident was opened during this run.")
        return
    labels = {f"{i.incident_id[:8]} - {i.severity} - {i.status}": i for i in on.incidents}
    incident = labels[st.selectbox("Incident", list(labels))]

    cols = st.columns(3)
    cols[0].markdown(_badge(incident.status, "#3B82F6"), unsafe_allow_html=True)
    cols[1].markdown(_badge(incident.severity, _CLASSIFICATION_COLOR.get(incident.severity, "#64748B")), unsafe_allow_html=True)
    cols[2].write(f"Probable attack: **{incident.probable_attack or 'not yet determined'}**")
    st.write(f"Affected assets: {', '.join(incident.affected_assets)}")

    st.subheader("Timeline")
    st.dataframe(pd.DataFrame(incident.timeline), use_container_width=True, hide_index=True)

    st.subheader("Detection scores for affected assets")
    rows = [r for r in on.detection_rows if r["sensor_id"] in incident.affected_assets]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if SUBSTATION in incident.affected_assets:
        st.subheader("Substation load: true vs. reported vs. dispatched")
        st.dataframe(pd.DataFrame(on.dispatch_rows), use_container_width=True, hide_index=True)

    st.subheader("Response actions")
    st.dataframe(pd.DataFrame([a.model_dump() for a in incident.response_actions]), use_container_width=True, hide_index=True)


def render_detection_analytics(on: RunTrace, aggregate: dict | None) -> None:
    sensors = sorted({r["sensor_id"] for r in on.detection_rows})
    sensor = st.selectbox("Sensor", sensors, index=sensors.index(SUBSTATION) if SUBSTATION in sensors else 0)
    df = pd.DataFrame([r for r in on.detection_rows if r["sensor_id"] == sensor]).set_index("tick")
    st.line_chart(df[["rule_score", "statistical_score", "ml_score", "physics_score", "risk_score"]])
    st.caption(f"Attack onset at tick {ATTACK_START_TICK}." if on.security_enabled else "Security disabled - detection still runs, containment does not.")

    det = (aggregate or {}).get("detection")
    if det is None:
        st.info("Run `python -m evaluation.harness` to populate detection rate and false-positive rate.")
        return
    cols = st.columns(2)
    cols[0].metric("Detection rate (aggregate)", f"{det['detection_rate']:.0%}")
    cols[1].metric("False-positive rate (aggregate)", f"{det['false_positive_rate']:.2%}")


def render_automation_center(on: RunTrace, off: RunTrace) -> None:
    st.caption("Automation mode: deterministic policy engine (config.settings.AUTONOMY_TIERS) - the LLM never sets auto_execute.")
    actions = [(i, a) for i in on.incidents for a in i.response_actions]
    executed = [(i, a) for i, a in actions if a.executed]
    pending = [(i, a) for i, a in actions if not a.executed]

    cols = st.columns(2)
    with cols[0]:
        st.subheader(f"Executed ({len(executed)})")
        st.dataframe(_action_table(executed), use_container_width=True, hide_index=True)
    with cols[1]:
        st.subheader(f"Held for approval ({len(pending)})")
        st.dataframe(_action_table(pending), use_container_width=True, hide_index=True)

    st.subheader("Security ON vs OFF - this run")
    cols = st.columns(3)
    cols[0].metric("Dispatch cost", f"${on.total_cost:,.2f}", delta=f"{on.total_cost - off.total_cost:+,.2f}", delta_color="off")
    cols[1].metric("Emissions (t CO2)", f"{on.total_emissions:,.3f}", delta=f"{on.total_emissions - off.total_emissions:+,.3f}", delta_color="off")
    cols[2].metric("Unnecessary generation (MWh)", f"{on.total_unnecessary_mwh:,.3f}", delta=f"{on.total_unnecessary_mwh - off.total_unnecessary_mwh:+,.3f}", delta_color="inverse")
    st.caption(
        "Unnecessary generation is the reliable cross-scenario signal (security ON never exceeds OFF). "
        "Cost and emissions are shown neutrally, not colored: for LOAD_SUPPRESSION, security ON restores "
        "dispatch to the true higher load, which costs more but corrects an unsafe under-generation - that "
        "is security working as intended, not a regression."
    )


def _action_table(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["incident", "type", "target", "risk"])
    return pd.DataFrame([{"incident": i.incident_id[:8], "type": a.type, "target": a.target, "risk": a.risk} for i, a in rows])
