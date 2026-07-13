"""Renders the five SOC dashboard panels (PRD Section 10). Each function takes the data
it needs (a RunTrace, and/or the loaded evaluation harness aggregate) and draws directly
into the current Streamlit container - kept separate from dashboard/app.py, which only
owns page setup, the sidebar, and driving a live run.
"""

from collections import Counter

import pandas as pd
import streamlit as st

from config import settings
from dashboard.live_run import RunTrace
from evaluation.harness import ATTACK_START_TICK, TICKS_PER_RUN
from simulator.grid import SUBSTATION

# Locked design tokens (PRD Section 4). Red is reserved for QUARANTINED and must never
# appear for a classification or incident severity, however critical - only the gateway
# status language below is allowed to use it.
_CLASSIFICATION_COLOR = {
    "NORMAL": "#8A94A3", "LOW": "#8A94A3",
    "OBSERVE": "#3B9EFF", "MEDIUM": "#3B9EFF",
    "SUSPICIOUS": "#D9A441",
    "HIGH_RISK": "#D9A441", "HIGH": "#D9A441",
    "CRITICAL": "#D9A441",
}
_STATUS_COLOR = {"TRUSTED": "#57A773", "ESTIMATED": "#D9A441", "QUARANTINED": "#E5484D"}
_ACTIVE_STATUSES = {"NEW", "TRIAGING", "INVESTIGATING", "CONTAINMENT_PENDING", "CONTAINED", "MONITORING"}
_SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
_MINUTES_PER_RUN = TICKS_PER_RUN * settings.TICK_SECONDS / 60


def _badge(label: str, color: str) -> str:
    return f'<span style="background:{color}22;color:{color};border:1px solid {color}66;border-radius:4px;padding:2px 8px;font-size:0.85em;font-weight:600;">{label}</span>'


def render_status_bar(on: RunTrace) -> None:
    active = [i for i in on.incidents if i.status in _ACTIVE_STATUSES]
    posture = max((i.severity for i in on.incidents), default="NOMINAL", key=lambda s: _SEVERITY_ORDER.index(s))
    counts = Counter(on.gateway_status.values())
    gateway = " &nbsp; ".join(
        f'<span style="color:{_STATUS_COLOR[status]}">{counts[status]} {status}</span>'
        for status in ("TRUSTED", "ESTIMATED", "QUARANTINED") if counts.get(status)
    )
    st.markdown(
        f"""<div class="rl-topbar">
            <div class="rl-topbar__item"><span class="rl-topbar__label">System posture</span><span class="rl-topbar__value">{posture}</span></div>
            <div class="rl-topbar__item"><span class="rl-topbar__label">Active incidents</span><span class="rl-topbar__value">{len(active)}</span></div>
            <div class="rl-topbar__item"><span class="rl-topbar__label">Gateway health</span><span class="rl-topbar__value">{gateway}</span></div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_threat_score_card(on: RunTrace) -> None:
    if not on.detection_rows:
        st.caption("No detection data for this run.")
        return
    last_tick = max(r["tick"] for r in on.detection_rows)
    row = max((r for r in on.detection_rows if r["tick"] == last_tick), key=lambda r: r["risk_score"])
    detectors = [("Rule", row["rule_score"]), ("Statistical", row["statistical_score"]), ("ML", row["ml_score"]), ("Physics", row["physics_score"])]
    bars = "".join(
        f"""<div class="rl-detector">
            <div class="rl-detector__label"><span>{name}</span><span class="rl-detector__value">{val:.2f}</span></div>
            <div class="rl-detector__track"><div class="rl-detector__fill" style="width:{val * 100:.0f}%"></div></div>
        </div>"""
        for name, val in detectors
    )
    color = _CLASSIFICATION_COLOR.get(row["classification"], "#8A94A3")
    st.markdown(
        f"""<div class="rl-card">
            <div class="rl-card__title">Unified threat score &middot; {row["sensor_id"]} &middot; tick {row["tick"]}</div>
            <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:10px;">
                <span class="rl-mono" style="font-size:1.8em;font-weight:700;color:{color};">{row["risk_score"]:.2f}</span>
                <span class="rl-badge" style="background:{color}22;color:{color};border:1px solid {color}66;">{row["classification"]}</span>
            </div>
            <div class="rl-detectors">{bars}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_detection_feed(on: RunTrace, limit: int = 12) -> None:
    rows = sorted((r for r in on.detection_rows if r["classification"] != "NORMAL"), key=lambda r: r["tick"], reverse=True)[:limit]
    if not rows:
        st.caption("No anomalous readings this run.")
        return
    items = "".join(
        f"""<div class="rl-feed__row" style="border-left-color:{_CLASSIFICATION_COLOR.get(r["classification"], "#8A94A3")}">
            <span class="rl-feed__tick">t{r["tick"]:03d}</span>
            <span class="rl-feed__sensor">{r["sensor_id"]}</span>
            <span class="rl-feed__class" style="color:{_CLASSIFICATION_COLOR.get(r["classification"], "#8A94A3")}">{r["classification"]}</span>
            <span class="rl-feed__score">{r["risk_score"]:.2f}</span>
        </div>"""
        for r in rows
    )
    st.markdown(f'<div class="rl-card"><div class="rl-card__title">Detection feed</div><div class="rl-feed">{items}</div></div>', unsafe_allow_html=True)


def render_gateway_state(on: RunTrace) -> None:
    if not on.gateway_status:
        st.caption("No gateway data for this run.")
        return
    tiles = "".join(
        f"""<div class="rl-gateway-tile" style="border-left-color:{_STATUS_COLOR[status]}">
            <div class="rl-gateway-tile__id">{sensor}</div>
            <div class="rl-gateway-tile__status" style="color:{_STATUS_COLOR[status]}">{status}</div>
            <div class="rl-gateway-tile__reason">{on.gateway_reasons.get(sensor, "")}</div>
        </div>"""
        for sensor, status in sorted(on.gateway_status.items())
    )
    st.markdown(f'<div class="rl-gateway-grid">{tiles}</div>', unsafe_allow_html=True)


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

    st.divider()
    card_col, feed_col = st.columns([3, 2])
    with card_col:
        render_threat_score_card(on)
    with feed_col:
        render_detection_feed(on)


_AGENT_SUMMARY = {
    "triage_agent": lambda o: f"{o.get('decision')} - {o.get('rationale', '')[:120]}",
    "investigation_agent": lambda o: f"probable attack: {o.get('probable_attack')} ({', '.join(o.get('matched_indicators', []))})",
    "response_agent": lambda o: f"{len(o.get('actions', []))} action(s) proposed",
    "analyst_agent": lambda o: o.get("executive_summary", "")[:160],
}


_PIPELINE_AGENTS = ["triage_agent", "investigation_agent", "response_agent", "analyst_agent"]
_PIPELINE_LABELS = {"triage_agent": "Triage", "investigation_agent": "Investigation", "response_agent": "Response", "analyst_agent": "Analyst"}


def render_agent_activity(on: RunTrace) -> None:
    if not on.decisions:
        st.info("No incident escalated during this run - nothing for the agents to act on.")
        return
    ordered = sorted(on.decisions, key=lambda d: d.timestamp)
    by_agent = {d.agent: d for d in ordered}
    live_agent = ordered[-1].agent

    stages = []
    for agent in _PIPELINE_AGENTS:
        decision = by_agent.get(agent)
        if decision is None:
            stages.append(f"""<div class="rl-pipeline__stage rl-pipeline__stage--pending">
                <div class="rl-pipeline__name">{_PIPELINE_LABELS[agent]}</div>
                <div class="rl-pipeline__body">Not reached</div>
            </div>""")
            continue
        summarize = _AGENT_SUMMARY.get(agent, lambda o: str(o))
        active_cls = " rl-pipeline__stage--active" if agent == live_agent else ""
        stages.append(f"""<div class="rl-pipeline__stage{active_cls}">
            <div class="rl-pipeline__name">{_PIPELINE_LABELS[agent]}</div>
            <div class="rl-pipeline__body">{summarize(decision.output)}</div>
            <div class="rl-pipeline__meta">{decision.duration_ms} ms &middot; {decision.confidence:.0%} confidence</div>
        </div>""")
    st.markdown(f'<div class="rl-pipeline">{"".join(stages)}</div>', unsafe_allow_html=True)

    for decision in ordered:
        with st.expander(f"{_PIPELINE_LABELS.get(decision.agent, decision.agent)} raw output"):
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


def _worst_dispatch_tick(off: RunTrace) -> dict | None:
    """The tick where the reported reading deviated furthest from truth - the attack's
    highest-impact moment, and the clearest single frame for a defense-off/defense-on
    comparison.
    """
    if not off.dispatch_rows:
        return None
    return max(off.dispatch_rows, key=lambda r: abs(r["reported_load"] - r["true_load"]))


def render_counterfactual(on: RunTrace, off: RunTrace) -> None:
    """Leads with the outcome - what the optimizer actually dispatched on, defense off
    versus defense on, at the attack's worst moment - then keeps the aggregate cost,
    emissions, and unnecessary-generation deltas underneath as supporting evidence.
    """
    worst = _worst_dispatch_tick(off)
    on_at_worst = next((r for r in on.dispatch_rows if worst and r["tick"] == worst["tick"]), None)
    if worst and on_at_worst and abs(worst["reported_load"] - worst["true_load"]) > 1e-6:
        off_dispatched = worst["dispatched_load"]
        on_dispatched = on_at_worst["dispatched_load"]
        on_label = "withheld" if on_dispatched is None else f"{on_dispatched:.2f} MW"
        on_note = "the optimizer receives nothing rather than a guess" if on_dispatched is None else "reconstructed from trusted peers, not the poisoned reading"
        st.markdown(
            f"""<div class="rl-card">
                <div class="rl-card__title">The attack's worst moment &middot; tick {worst["tick"]}</div>
                <div class="rl-counterfactual">
                    <div class="rl-counterfactual__side">
                        <div class="rl-counterfactual__label" style="color:{_STATUS_COLOR["QUARANTINED"]}">Defense OFF</div>
                        <div class="rl-counterfactual__value rl-mono">{off_dispatched:.2f} MW</div>
                        <div class="rl-counterfactual__note">the optimizer dispatches on the poisoned reading</div>
                    </div>
                    <div class="rl-counterfactual__side">
                        <div class="rl-counterfactual__label" style="color:{_STATUS_COLOR["TRUSTED"]}">Defense ON</div>
                        <div class="rl-counterfactual__value rl-mono">{on_label}</div>
                        <div class="rl-counterfactual__note">{on_note}</div>
                    </div>
                    <div class="rl-counterfactual__side">
                        <div class="rl-counterfactual__label">True load</div>
                        <div class="rl-counterfactual__value rl-mono">{worst["true_load"]:.2f} MW</div>
                        <div class="rl-counterfactual__note">reported: {worst["reported_load"]:.2f} MW</div>
                    </div>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        st.caption("No dispatch deviation this run - the reported load matched truth throughout.")

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
