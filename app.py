"""
Recovery Copilot dashboard — Streamlit frontend over the Python agent
pipeline. Run with:

    streamlit run app.py
"""
from __future__ import annotations

import os
import tempfile

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from agent.audit import AuditTrail
from agent.classifier import train_default_model
from agent.messenger import generate_message, synthesize_voice
from agent.pipeline import run_pipeline
from agent.policy import decide
from data.generate_data import generate

# --- palette (dataviz skill reference palette, light mode) ------------------
BLUE = "#2a78d6"
BLUE_LIGHT = "#6da7ec"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
STATUS_CRITICAL = "#d03b3b"

st.set_page_config(page_title="Recovery Copilot", page_icon="\U0001F4B8", layout="wide")


@st.cache_resource(show_spinner="Training recoverability model on simulated historical data...")
def get_model():
    return train_default_model()


@st.cache_data(show_spinner="Generating batch and running the agent pipeline...")
def get_run(seed: int):
    df = generate(seed=seed)
    model = get_model()
    results, summary, _, systemic_issues = run_pipeline(df, model=model)
    return df, results, summary, systemic_issues


# ---------------------------------------------------------------- sidebar ---
st.sidebar.title("Recovery Copilot")
st.sidebar.caption("AI Revenue Recovery agent — Razorpay AI Buildathon")
seed = st.sidebar.number_input("Batch seed", min_value=1, max_value=9999, value=42, step=1)
st.sidebar.caption("Change the seed to run the agent fresh on a new synthetic batch of at-risk transactions.")
st.sidebar.divider()
st.sidebar.markdown(
    "**The Bar this demo targets:**\n"
    "- Measured ₹ recovered vs a naive baseline\n"
    "- Compliant escalation with stopping rules\n"
    "- Complete audit trail per transaction\n"
    "- Real recovery *execution*, not just detection"
)
st.sidebar.divider()
st.sidebar.markdown(
    "**Example directions covered:**\n"
    "- Payment degradation → root cause → recovery action\n"
    "- Checkout drop-off recovery\n"
    "- Failed-subscription recovery\n"
    "- B2B receivables chaser\n"
    "- Mandate retry sequencer\n"
    "- Hinglish voice recovery\n"
    "- Promise-to-pay tracker"
)

df, results, summary, systemic_issues = get_run(int(seed))
audit = AuditTrail()
model = get_model()

st.title("\U0001F4B8 Recovery Copilot")
st.caption(
    "Detects revenue at risk (failed payments, checkout drop-off, subscription/mandate failures, "
    "overdue invoices), decides the right bounded intervention, and executes it — with a full "
    "audit trail and compliance stopping rules."
)

# --------------------------------------------------------- systemic banner --
if systemic_issues:
    for issue in systemic_issues.values():
        st.markdown(
            f"""<div style="border-left:4px solid {STATUS_CRITICAL}; background:#fdf1f0;
            padding:10px 14px; border-radius:4px; margin-bottom:10px;">
            <span style="color:{STATUS_CRITICAL}; font-weight:600;">⚠ Systemic issue detected — root-cause analyzer</span><br/>
            <span style="color:{INK_PRIMARY};">{issue.note}</span>
            </div>""",
            unsafe_allow_html=True,
        )

# ------------------------------------------------------------- KPI row -----
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total revenue at risk", f"₹{summary['total_at_risk']:,.0f}", help="Sum of all at-risk transactions in this batch")
k2.metric(
    "Recovered by agent", f"₹{summary['agent_recovered']:,.0f}",
    delta=f"+₹{summary['uplift_amount']:,.0f} vs baseline",
)
k3.metric(
    "Recovery rate", f"{summary['agent_recovery_rate']:.1f}%",
    delta=f"+{summary['agent_recovery_rate'] - summary['baseline_recovery_rate']:.1f}pp vs baseline",
)
k4.metric(
    "Compliance violations avoided", summary["baseline_compliance_violations_avoided"],
    help="Do-not-contact / max-attempt violations the naive baseline would have committed",
)
k5.metric(
    "Promises kept / broken", f"{summary['promises_kept']} / {summary['promises_broken']}",
    help="Promise-to-pay tracker: broken promises are auto-escalated to a human agent, not dropped",
)

st.divider()

# --------------------------------------------------- recovered: before/after
left, right = st.columns([3, 2])

with left:
    st.subheader("Recovered revenue: baseline vs Recovery Copilot")
    agg = (
        results.groupby("risk_type")[["baseline_recovered_amount", "agent_recovered_amount"]]
        .sum()
        .reset_index()
        .sort_values("agent_recovered_amount")
    )
    fig = go.Figure()
    for _, r in agg.iterrows():
        fig.add_trace(go.Scatter(
            x=[r["baseline_recovered_amount"], r["agent_recovered_amount"]],
            y=[r["risk_type"], r["risk_type"]],
            mode="lines", line=dict(color=GRID, width=3), showlegend=False, hoverinfo="skip",
        ))
    fig.add_trace(go.Scatter(
        x=agg["baseline_recovered_amount"], y=agg["risk_type"], mode="markers",
        name="Baseline (before)", marker=dict(color=BLUE_LIGHT, size=13),
        hovertemplate="Baseline: ₹%{x:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=agg["agent_recovered_amount"], y=agg["risk_type"], mode="markers",
        name="Recovery Copilot (after)", marker=dict(color=BLUE, size=16),
        hovertemplate="Recovery Copilot: ₹%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="#fcfcfb", paper_bgcolor="#fcfcfb",
        font=dict(color=INK_PRIMARY),
        xaxis=dict(title="Recovered amount (₹)", gridcolor=GRID, zeroline=False),
        yaxis=dict(title="", gridcolor=GRID),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("What the agent decided")
    action_counts = results["agent_action"].value_counts().sort_values()
    fig2 = px.bar(
        x=action_counts.values, y=action_counts.index, orientation="h",
        labels={"x": "Transactions", "y": ""},
        color_discrete_sequence=[BLUE],
    )
    fig2.update_layout(
        height=320, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="#fcfcfb", paper_bgcolor="#fcfcfb",
        font=dict(color=INK_PRIMARY),
        xaxis=dict(gridcolor=GRID, zeroline=False),
        yaxis=dict(gridcolor=GRID),
        showlegend=False,
    )
    st.plotly_chart(fig2, width="stretch")

st.divider()

# ------------------------------------------------------- transaction table -
st.subheader("Transaction queue")
f1, f2, f3 = st.columns(3)
risk_filter = f1.multiselect("Risk type", sorted(results["risk_type"].unique()))
action_filter = f2.multiselect("Agent action", sorted(results["agent_action"].unique()))
segment_filter = f3.multiselect("Customer segment", sorted(results["customer_segment"].unique()))

view = results.copy()
if risk_filter:
    view = view[view["risk_type"].isin(risk_filter)]
if action_filter:
    view = view[view["agent_action"].isin(action_filter)]
if segment_filter:
    view = view[view["customer_segment"].isin(segment_filter)]

st.dataframe(
    view[[
        "transaction_id", "risk_type", "failure_reason", "amount", "customer_segment",
        "recoverability_score", "agent_action", "agent_channel", "agent_retry_method",
        "promise_to_pay_status", "agent_resolved", "agent_recovered_amount",
    ]].sort_values("recoverability_score", ascending=False),
    width="stretch", height=280,
)

st.divider()

# ----------------------------------------------------------- drill-down ----
st.subheader("Inspect one decision")
txn_id = st.selectbox("Transaction ID", view["transaction_id"].tolist() if not view.empty else results["transaction_id"].tolist())

if txn_id:
    row = df[df["transaction_id"] == txn_id].iloc[0]
    res_row = results[results["transaction_id"] == txn_id].iloc[0]
    decision = decide(row, float(res_row["recoverability_score"]), systemic_issues)

    d1, d2 = st.columns([1, 1])
    with d1:
        st.markdown(f"**Customer:** {row['customer_name']} ({row['customer_segment']})")
        st.markdown(f"**Amount:** ₹{row['amount']:,.0f} · **Risk type:** {row['risk_type']}")
        st.markdown(f"**Failure reason:** {row['failure_reason']} · **Method:** {row['payment_method']}")
        st.markdown(f"**Previous attempts:** {row['previous_attempts']} · **Recoverability score:** {res_row['recoverability_score']:.2f}")

        st.markdown("**Why this score — top contributing factors:**")
        for feat, contrib in model.explain(row):
            direction = "↑ increases" if contrib > 0 else "↓ decreases"
            st.markdown(f"- `{feat}` — {direction} recoverability ({contrib:+.2f})")

    with d2:
        st.markdown(f"**Agent decision:** `{decision.action}`" + (f" via `{decision.channel}`" if decision.channel else ""))
        if decision.retry_method:
            st.markdown(f"**Retry sequencer:** `{decision.retry_method}` method, in {decision.retry_delay_hours}h")
        st.markdown("**Reasoning:**")
        for r in decision.reasoning:
            st.markdown(f"- {r}")

        if res_row["promise_to_pay_status"] in ("kept", "broken"):
            icon = "✅" if res_row["promise_to_pay_status"] == "kept" else "🚨"
            st.markdown(f"**Promise-to-pay tracker:** {icon} {res_row['promise_to_pay_note']}")

        if decision.action == "SEND_MESSAGE":
            msg = generate_message(row, decision)
            st.markdown("**Generated message:**")
            st.info(msg)
            if decision.channel == "voice_hinglish":
                if st.button("\U0001F50A Play agent's voice message"):
                    with tempfile.TemporaryDirectory() as tmp:
                        out_path = os.path.join(tmp, "message.wav")
                        ok = synthesize_voice(msg, out_path)
                        if ok:
                            with open(out_path, "rb") as f:
                                st.audio(f.read(), format="audio/wav")
                        else:
                            st.warning("Offline TTS engine not available in this environment — message text shown above.")

    st.markdown("**Full audit trail for this transaction:**")
    trail = audit.for_transaction(txn_id)
    if not trail.empty:
        st.dataframe(trail[["timestamp", "action", "reasoning", "stopping_rule_triggered", "systemic_issue_note"]], width="stretch")
    else:
        st.caption("No audit entries found — re-run the batch to regenerate the log.")
