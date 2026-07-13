"""Single CSS injection point for the hand-built panels in dashboard/panels.py (PRD
Section 4/5). Everything here targets our own `rl-*` classes, never Streamlit's
generated/hashed class names, so it survives Streamlit upgrades.
"""

import streamlit as st

_CSS = """
<style>
:root {
    --rl-bg: #0E1116;
    --rl-surface: #161A21;
    --rl-surface-raised: #1C222B;
    --rl-border: #2A313B;
    --rl-text: #E8EDF4;
    --rl-text-muted: #8A94A3;
    --rl-accent: #3B9EFF;
    --rl-trusted: #57A773;
    --rl-estimated: #D9A441;
    --rl-quarantined: #E5484D;
    --rl-mono: "IBM Plex Mono", monospace;
}

.rl-mono {
    font-family: var(--rl-mono);
    font-variant-numeric: tabular-nums;
}

/* Top status bar */
.rl-topbar {
    display: flex;
    gap: 28px;
    align-items: center;
    background: var(--rl-surface);
    border: 1px solid var(--rl-border);
    border-radius: 6px;
    padding: 10px 18px;
    margin-bottom: 14px;
}
.rl-topbar__item { display: flex; flex-direction: column; gap: 2px; }
.rl-topbar__label {
    color: var(--rl-text-muted);
    font-size: 0.7em;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.rl-topbar__value {
    font-family: var(--rl-mono);
    font-variant-numeric: tabular-nums;
    font-size: 1.05em;
    font-weight: 600;
}

/* Generic dense card */
.rl-card {
    background: var(--rl-surface-raised);
    border: 1px solid var(--rl-border);
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 10px;
}
.rl-card__title {
    color: var(--rl-text-muted);
    font-size: 0.72em;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 8px;
}

/* Threat score card: detector contribution bars */
.rl-detectors { display: flex; gap: 18px; }
.rl-detector { flex: 1; min-width: 0; }
.rl-detector__label {
    color: var(--rl-text-muted);
    font-size: 0.72em;
    display: flex;
    justify-content: space-between;
    margin-bottom: 4px;
}
.rl-detector__value { font-family: var(--rl-mono); font-variant-numeric: tabular-nums; }
.rl-detector__track {
    height: 5px;
    background: var(--rl-border);
    border-radius: 3px;
    overflow: hidden;
}
.rl-detector__fill { height: 100%; border-radius: 3px; background: var(--rl-accent); }

/* Detection feed */
.rl-feed { max-height: 320px; overflow-y: auto; }
.rl-feed__row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 10px;
    border-left: 3px solid var(--rl-border);
    border-bottom: 1px solid var(--rl-border);
    font-size: 0.82em;
}
.rl-feed__tick {
    font-family: var(--rl-mono);
    font-variant-numeric: tabular-nums;
    color: var(--rl-text-muted);
    min-width: 3.5em;
}
.rl-feed__sensor { flex: 1; }
.rl-feed__class { font-weight: 600; min-width: 6.5em; }
.rl-feed__score {
    font-family: var(--rl-mono);
    font-variant-numeric: tabular-nums;
    min-width: 3.5em;
    text-align: right;
}

/* Agent pipeline */
.rl-pipeline { display: flex; gap: 10px; }
.rl-pipeline__stage {
    flex: 1;
    min-width: 0;
    background: var(--rl-surface-raised);
    border: 1px solid var(--rl-border);
    border-radius: 6px;
    padding: 10px 12px;
}
.rl-pipeline__stage--active { border-color: var(--rl-accent); }
.rl-pipeline__stage--pending { opacity: 0.45; }
.rl-pipeline__name {
    font-size: 0.75em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 6px;
}
.rl-pipeline__body {
    color: var(--rl-text-muted);
    font-size: 0.82em;
    line-height: 1.4;
}
.rl-pipeline__meta {
    font-family: var(--rl-mono);
    font-variant-numeric: tabular-nums;
    color: var(--rl-text-muted);
    font-size: 0.75em;
    margin-top: 6px;
}

/* Gateway state view */
.rl-gateway-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 10px;
}
.rl-gateway-tile {
    background: var(--rl-surface-raised);
    border: 1px solid var(--rl-border);
    border-left: 3px solid var(--rl-border);
    border-radius: 6px;
    padding: 10px 12px;
}
.rl-gateway-tile__id {
    font-family: var(--rl-mono);
    font-weight: 600;
    font-size: 0.9em;
}
.rl-gateway-tile__status {
    font-size: 0.72em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 4px;
}
.rl-gateway-tile__reason {
    color: var(--rl-text-muted);
    font-size: 0.72em;
    line-height: 1.35;
    margin-top: 6px;
}

/* Counterfactual headline: defense off vs defense on at the attack's worst tick */
.rl-counterfactual { display: flex; gap: 18px; }
.rl-counterfactual__side { flex: 1; min-width: 0; }
.rl-counterfactual__label {
    font-size: 0.72em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
}
.rl-counterfactual__value {
    font-size: 1.4em;
    font-weight: 700;
}
.rl-counterfactual__note {
    color: var(--rl-text-muted);
    font-size: 0.78em;
    margin-top: 2px;
}

/* Status-colored badge, reused across panels */
.rl-badge {
    display: inline-flex;
    padding: 1px 8px;
    border-radius: 4px;
    font-size: 0.78em;
    font-weight: 600;
}
</style>
"""


def inject() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
