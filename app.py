"""
Recovery Copilot dashboard — Streamlit frontend over the Python agent
pipeline. Run with:

    streamlit run app.py
"""
from __future__ import annotations

import os
import random
import tempfile
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from agent.audit import AuditTrail
from agent.classifier import train_default_model
from agent.cost_model import estimate_cost
from agent.messenger import generate_message, synthesize_voice
from agent.pipeline import run_pipeline
from agent.policy import decide
from agent.razorpay_client import build_call
from agent.workflow import run_workflow
from data.generate_data import CUSTOMER_SEGMENTS, FAILURE_REASONS, PAYMENT_METHODS, RISK_TYPES, generate

# --- palette (dataviz skill reference palette, light mode) ------------------
BLUE = "#2a78d6"
BLUE_LIGHT = "#6da7ec"
ORANGE = "#eb6834"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
STATUS_CRITICAL = "#d03b3b"
STATUS_GOOD = "#0ca30c"
SURFACE = "#fcfcfb"

# human-readable labels -- the raw action/status codes (SEND_MESSAGE,
# ESCALATE_OPS...) are what the code calls them, not what a person reads
ACTION_LABEL = {
    "SEND_MESSAGE": "Sent a nudge",
    "RETRY_PAYMENT": "Retried the payment",
    "ESCALATE_HUMAN": "Escalated to a human agent",
    "ESCALATE_OPS": "Flagged to ops (system issue)",
    "STOP": "Left alone (not worth pursuing)",
}
RISK_TYPE_LABEL = {
    "payment_failure": "Payment failures",
    "checkout_abandonment": "Checkout drop-offs",
    "subscription_failure": "Subscription failures",
    "invoice_overdue": "Overdue invoices",
}
# plain-language phrase for each systemic-issue failure reason -- without
# this, two DIFFERENT netbanking issues (e.g. bank_timeout vs
# mandate_bank_error) both read as "netbanking payments are failing" with
# just a different multiplier, which looks like the same fact contradicting
# itself rather than two distinct problems
SYSTEMIC_REASON_PHRASE = {
    "bank_timeout": "timing out",
    "network_drop": "dropping mid-payment",
    "mandate_bank_error": "erroring on auto-pay (mandate) charges",
    "issuer_declined": "being declined by the issuing bank",
}

st.set_page_config(page_title="Recovery Copilot", page_icon="\U0001F4B8", layout="wide")

st.markdown(
    """<style>
    div[data-testid="stMetric"] { background: #f9f9f7; border: 1px solid #e1e0d9; border-radius: 8px; padding: 12px 14px; }
    div[data-testid="stMetricValue"] { font-size: 1.5rem; }
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="Training recoverability model on simulated historical data...")
def get_model():
    return train_default_model()


@st.cache_data(show_spinner="Generating batch and running the agent pipeline...")
def get_run(seed: int):
    df = generate(seed=seed)
    model = get_model()
    results, summary, _, systemic_issues = run_pipeline(df, model=model)
    return df, results, summary, systemic_issues


@st.cache_data(show_spinner="Simulating the multi-day recovery workflow...")
def get_workflow(seed: int, n_days: int):
    df = generate(seed=seed)
    model = get_model()
    return run_workflow(
        df, model, n_days=n_days,
        db_path=f"data/workflow_state_{seed}.db",
        audit_path=f"data/workflow_audit_log_{seed}.jsonl",
    )


# ---------------------------------------------------------------- sidebar ---
st.sidebar.title("\U0001F4B8 Recovery Copilot")
st.sidebar.caption("AI Revenue Recovery agent — Razorpay AI Buildathon")

if "seed" not in st.session_state:
    st.session_state["seed"] = 42
if st.sidebar.button("\U0001F3B2 Randomize batch", width="stretch"):
    st.session_state["seed"] = random.randint(1, 9999)

seed = st.sidebar.number_input("Batch seed", min_value=1, max_value=9999, step=1, key="seed")
st.sidebar.caption("Change the seed (or hit Randomize) to run the agent fresh on a new synthetic batch — "
                    "everything below recomputes, live, from that new data.")
st.sidebar.caption(f"\U0001F7E2 Recomputed at {datetime.now().strftime('%H:%M:%S')}")
with st.sidebar.expander("What is this agent doing? (for reviewers)"):
    st.markdown(
        "**Targets Razorpay's own bar for this track:**\n"
        "- Measured ₹ recovered vs a naive baseline\n"
        "- Compliant escalation with stopping rules\n"
        "- Complete audit trail per transaction\n"
        "- Real recovery *execution*, not just detection\n\n"
        "**Covers every named example direction:** payment root-cause "
        "analysis, checkout drop-off recovery, failed-subscription recovery, "
        "B2B receivables chasing, a mandate retry sequencer, Hinglish voice "
        "recovery, and a promise-to-pay tracker."
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

tab_live, tab_overview, tab_workflow, tab_investigate, tab_merchant = st.tabs(
    ["\U0001F9EA Try it live", "\U0001F4CA Overview", "\U0001F5D3️ Multi-day workflow", "\U0001F50D Investigate", "\U0001F3EA Merchant view"]
)

# ================================================================ TRY LIVE ==
with tab_live:
    st.subheader("Feed the agent a transaction yourself")
    st.caption(
        "This isn't pre-computed — change anything below and the agent re-scores, "
        "re-decides, and re-explains itself immediately, on your input, using the "
        "same classifier/policy/cost-model/Razorpay-mapping code as everywhere else "
        "on this page."
    )

    lc1, lc2, lc3 = st.columns(3)
    with lc1:
        live_risk_type = st.selectbox("Risk type", RISK_TYPES, format_func=lambda x: RISK_TYPE_LABEL.get(x, x), key="live_risk_type")
        live_failure_reason = st.selectbox("Failure reason", FAILURE_REASONS[live_risk_type], key="live_failure_reason")
        live_amount = st.number_input("Amount (₹)", min_value=50.0, max_value=250000.0, value=5000.0, step=50.0, key="live_amount")
    with lc2:
        live_payment_method = st.selectbox("Payment method", PAYMENT_METHODS, key="live_payment_method")
        live_segment = st.selectbox("Customer segment", CUSTOMER_SEGMENTS, index=1, key="live_segment")
        live_attempts = st.slider("Previous attempts", 0, 4, 0, key="live_attempts")
    with lc3:
        live_hour = st.slider("Customer's local hour right now", 0, 23, 12, key="live_hour")
        live_dnc = st.checkbox("Customer opted out (do-not-contact)", key="live_dnc")
        st.caption("Tip: set attempts to 3+ to see the max-attempts stopping rule fire, "
                   "pick a (payment method, reason) pair matching a banner on the "
                   "Overview tab to see it route to ops instead of the customer, or push "
                   "the amount above ₹75,000 on any reason to see value-based triage "
                   "override the usual routing to a human agent.")

    live_row = pd.Series({
        "transaction_id": "live_test_0001",
        "customer_name": "Test Customer",
        "amount": float(live_amount),
        "currency": "INR",
        "risk_type": live_risk_type,
        "failure_reason": live_failure_reason,
        "payment_method": live_payment_method,
        "customer_segment": live_segment,
        "previous_attempts": int(live_attempts),
        "do_not_contact": bool(live_dnc),
        "customer_local_hour": int(live_hour),
        "days_since_event": 0,
        "_true_recoverable_prob": 0.0,
    })
    live_score = float(model.predict_proba(pd.DataFrame([live_row]))[0])
    live_decision = decide(live_row, live_score, systemic_issues)

    st.divider()
    r1, r2 = st.columns([1, 1])
    with r1:
        with st.container(border=True):
            st.markdown(f"### Recoverability score: **{live_score:.2f}**")
            st.progress(min(max(live_score, 0.0), 1.0))
            for feat, contrib in model.explain(live_row):
                direction = "↑ increases" if contrib > 0 else "↓ decreases"
                st.markdown(f"- `{feat}` — {direction} recoverability ({contrib:+.2f})")

    with r2:
        with st.container(border=True):
            action_color = STATUS_CRITICAL if live_decision.action == "STOP" else STATUS_GOOD
            st.markdown(
                f"### Decision: <span style='color:{action_color}'>{ACTION_LABEL.get(live_decision.action, live_decision.action)}</span>"
                + (f" via `{live_decision.channel}`" if live_decision.channel else ""),
                unsafe_allow_html=True,
            )
            if live_decision.retry_method:
                st.markdown(f"**Retry sequencer:** `{live_decision.retry_method}` method, in {live_decision.retry_delay_hours}h")
            st.markdown(f"**Estimated cost:** ₹{estimate_cost(live_decision):.2f}")
            st.markdown("**Reasoning:**")
            for r in live_decision.reasoning:
                st.markdown(f"- {r}")

    if live_decision.action == "SEND_MESSAGE":
        st.markdown("**Message the agent would send:**")
        st.info(generate_message(live_row, live_decision))

    live_call = build_call(live_row, live_decision)
    if live_call is not None:
        with st.expander("Razorpay API call this would trigger"):
            st.code(f"{live_call.method} {live_call.path}", language="text")
            st.json(live_call.payload)
            st.caption(live_call.note)

# =============================================================== OVERVIEW ===
with tab_overview:
    # --------------------------------------------------- systemic issues ----
    with st.container(border=True):
        if systemic_issues:
            st.markdown(f"#### ⚠️ {len(systemic_issues)} systemic issue(s) detected right now")
            st.caption("The agent is pausing customer-facing retries for these — the problem is on the bank/gateway side, not the customer's.")
            for issue in systemic_issues.values():
                st.markdown(
                    f"- **{issue.payment_method.upper()} · {issue.failure_reason.replace('_', ' ')}** — "
                    f"**{issue.ratio:.1f}x** its normal rate ({issue.recent_count} in the last day). "
                    f"Retries paused, ops alerted."
                )
        else:
            st.markdown("#### ✅ No systemic issues detected")
            st.caption("All failure patterns are within their normal range this batch.")

    st.write("")

    # ------------------------------------------------------------ KPIs -----
    with st.container(border=True):
        k1, k2, k3 = st.columns(3)
        k1.metric("Total revenue at risk", f"₹{summary['total_at_risk']:,.0f}", help="Sum of all at-risk transactions in this batch")
        k2.metric(
            "Recovered (gross)", f"₹{summary['agent_recovered']:,.0f}",
            delta=f"+₹{summary['uplift_amount']:,.0f} vs baseline",
        )
        k3.metric(
            "Recovery rate", f"{summary['agent_recovery_rate']:.1f}%",
            delta=f"+{summary['agent_recovery_rate'] - summary['baseline_recovery_rate']:.1f}pp vs baseline",
        )
        k4, k5, k6 = st.columns(3)
        k4.metric(
            "Net recovered (after cost)", f"₹{summary['agent_net_recovered']:,.0f}",
            delta=f"+₹{summary['net_uplift_amount']:,.0f} vs baseline net",
            help=f"Gross recovered minus intervention cost (₹{summary['agent_intervention_cost']:,.0f} spent) "
                 f"— recovering more only counts if it didn't cost more than it was worth",
        )
        k5.metric(
            "Compliance violations avoided", summary["baseline_compliance_violations_avoided"],
            help="Do-not-contact / max-attempt violations the naive baseline would have committed",
        )
        k6.metric(
            "Promises kept / broken", f"{summary['promises_kept']} / {summary['promises_broken']}",
            help="Promise-to-pay tracker: broken promises are auto-escalated to a human agent, not dropped",
        )

    st.write("")

    # ------------------------------------------------ recovered by category -
    st.subheader("Recovered revenue by category: baseline vs Recovery Copilot")
    agg = (
        results.groupby("risk_type")[["baseline_recovered_amount", "agent_recovered_amount"]]
        .sum().reset_index()
    )
    agg["risk_label"] = agg["risk_type"].map(RISK_TYPE_LABEL).fillna(agg["risk_type"])
    agg = agg.sort_values("agent_recovered_amount")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=agg["risk_label"], x=agg["baseline_recovered_amount"], orientation="h",
        name="Baseline (before)", marker_color=BLUE_LIGHT,
        hovertemplate="Baseline: ₹%{x:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=agg["risk_label"], x=agg["agent_recovered_amount"], orientation="h",
        name="Recovery Copilot (after)", marker_color=BLUE,
        hovertemplate="Recovery Copilot: ₹%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        barmode="group", height=300, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, font=dict(color=INK_PRIMARY),
        xaxis=dict(title="Recovered amount (₹)", gridcolor=GRID, zeroline=False),
        yaxis=dict(title=""),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    st.plotly_chart(fig, width="stretch")

    total_uplift_pct = summary["uplift_pct"]
    if pd.notna(total_uplift_pct):
        st.caption(f"Across all categories: **{total_uplift_pct:+.0f}%** more recovered than the naive baseline on the identical batch.")

    st.write("")

    # ------------------------------------------------------ what it decided -
    st.subheader("What the agent decided, and why")
    action_counts = results["agent_action"].value_counts()
    action_labels = [ACTION_LABEL.get(a, a) for a in action_counts.index]

    fig2 = go.Figure(go.Bar(
        x=action_counts.values, y=action_labels, orientation="h",
        marker_color=BLUE, customdata=action_counts.index,
        hovertemplate="%{y}: %{x} transactions<extra></extra>",
    ))
    fig2.update_layout(
        height=280, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, font=dict(color=INK_PRIMARY),
        xaxis=dict(title="Transactions", gridcolor=GRID, zeroline=False),
        yaxis=dict(title="", categoryorder="total ascending"),
    )
    event = st.plotly_chart(fig2, width="stretch", on_select="rerun", key="action_chart", selection_mode="points")

    # click a bar to see a real example of that decision -- safe fallback if
    # the selection payload's shape ever differs from what's expected here
    clicked_action = None
    try:
        points = event["selection"]["points"] if event else []
        if points:
            clicked_action = points[0]["customdata"][0] if isinstance(points[0].get("customdata"), list) else points[0].get("customdata")
    except Exception:
        clicked_action = None

    if clicked_action and clicked_action in results["agent_action"].values:
        example = results[results["agent_action"] == clicked_action].iloc[0]
        st.info(
            f"**Example — {ACTION_LABEL.get(clicked_action, clicked_action)}:** "
            f"transaction `{example['transaction_id']}`, a ₹{example['amount']:,.0f} "
            f"{RISK_TYPE_LABEL.get(example['risk_type'], example['risk_type']).lower()} "
            f"case ({example['failure_reason'].replace('_', ' ')}). "
            f"See the **Investigate** tab to look up this transaction's full reasoning."
        )
    else:
        st.caption("Click a bar above to see a real example of that decision.")

# ============================================================== WORKFLOW ====
with tab_workflow:
    st.subheader("Multi-day workflow simulation")
    st.caption(
        "The Overview tab is one stateless pass. This runs the same batch through "
        "the classifier + policy + simulator stack across several simulated days, "
        "persisting each transaction's state — so the retry sequencer actually "
        "advances step by step and a promise-to-pay deadline actually arrives and "
        "gets checked, instead of every run starting from attempt zero."
    )
    n_days = st.slider("Simulated days", min_value=2, max_value=10, value=5)
    daily = get_workflow(int(seed), n_days)

    wf_fig = go.Figure()
    wf_fig.add_trace(go.Scatter(
        x=daily["day"], y=daily["cumulative_recovered"], mode="lines+markers",
        line=dict(color=BLUE, width=2), marker=dict(color=BLUE, size=9),
        fill="tozeroy", fillcolor="rgba(42,120,214,0.08)",
        hovertemplate="Day %{x}: ₹%{y:,.0f} recovered so far<extra></extra>",
    ))
    wf_fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, font=dict(color=INK_PRIMARY),
        xaxis=dict(title="Simulated day", gridcolor=GRID, zeroline=False, dtick=1),
        yaxis=dict(title="Cumulative ₹ recovered", gridcolor=GRID),
        showlegend=False,
    )
    st.plotly_chart(wf_fig, width="stretch")

    last_day = daily.iloc[-1]
    with st.container(border=True):
        st.markdown(
            f"By day **{int(last_day['day'])}**: **{int(last_day['cumulative_resolved'])}** of "
            f"{len(df)} transactions resolved, **₹{last_day['cumulative_recovered']:,.0f}** recovered — "
            f"more than the single-pass total on the Overview tab, because a real workflow gets "
            f"multiple scheduled chances (retry steps, promise deadlines) a one-shot decision doesn't."
        )
    with st.expander("Day-by-day detail"):
        st.dataframe(daily, width="stretch")

# ============================================================ INVESTIGATE ===
with tab_investigate:
    st.subheader("Transaction queue")
    f1, f2, f3 = st.columns(3)
    risk_filter = f1.multiselect("Risk type", sorted(results["risk_type"].unique()),
                                  format_func=lambda x: RISK_TYPE_LABEL.get(x, x))
    action_filter = f2.multiselect("Agent action", sorted(results["agent_action"].unique()),
                                    format_func=lambda x: ACTION_LABEL.get(x, x))
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
            "promise_to_pay_status", "agent_resolved", "agent_recovered_amount", "agent_intervention_cost",
        ]].sort_values("recoverability_score", ascending=False),
        width="stretch", height=280,
    )

    st.divider()

    st.subheader("Inspect one decision")
    txn_id = st.selectbox("Transaction ID", view["transaction_id"].tolist() if not view.empty else results["transaction_id"].tolist())

    if txn_id:
        row = df[df["transaction_id"] == txn_id].iloc[0]
        res_row = results[results["transaction_id"] == txn_id].iloc[0]
        decision = decide(row, float(res_row["recoverability_score"]), systemic_issues)

        d1, d2 = st.columns([1, 1])
        with d1:
            with st.container(border=True):
                st.markdown(f"**Customer:** {row['customer_name']} ({row['customer_segment']})")
                st.markdown(f"**Amount:** ₹{row['amount']:,.0f} · **Risk type:** {RISK_TYPE_LABEL.get(row['risk_type'], row['risk_type'])}")
                st.markdown(f"**Failure reason:** {row['failure_reason'].replace('_', ' ')} · **Method:** {row['payment_method']}")
                st.markdown(f"**Previous attempts:** {row['previous_attempts']} · **Recoverability score:** {res_row['recoverability_score']:.2f}")

                st.markdown("**Why this score — top contributing factors:**")
                for feat, contrib in model.explain(row):
                    direction = "↑ increases" if contrib > 0 else "↓ decreases"
                    st.markdown(f"- `{feat}` — {direction} recoverability ({contrib:+.2f})")

        with d2:
            with st.container(border=True):
                st.markdown(f"**Agent decision:** {ACTION_LABEL.get(decision.action, decision.action)}"
                            + (f" via `{decision.channel}`" if decision.channel else ""))
                if decision.retry_method:
                    st.markdown(f"**Retry sequencer:** `{decision.retry_method}` method, in {decision.retry_delay_hours}h")
                st.markdown(f"**Estimated intervention cost:** ₹{res_row['agent_intervention_cost']:.2f}")
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

                razorpay_call = build_call(row, decision)
                if razorpay_call is not None:
                    with st.expander("Razorpay API call this would trigger"):
                        st.code(f"{razorpay_call.method} {razorpay_call.path}", language="text")
                        st.json(razorpay_call.payload)
                        st.caption(razorpay_call.note)

        st.markdown("**Full audit trail for this transaction:**")
        trail = audit.for_transaction(txn_id)
        if not trail.empty:
            st.dataframe(trail[["timestamp", "action", "reasoning", "stopping_rule_triggered", "systemic_issue_note"]], width="stretch")
        else:
            st.caption("No audit entries found — re-run the batch to regenerate the log.")

# ================================================================ MERCHANT ==
with tab_merchant:
    st.caption("A simplified view — what a merchant using Recovery Copilot would actually see, not the technical detail above.")

    st.markdown(f"## This batch, Recovery Copilot recovered **₹{summary['agent_net_recovered']:,.0f}** for you")
    st.markdown(
        f"out of ₹{summary['total_at_risk']:,.0f} that was at risk across {summary['n_transactions']} transactions "
        f"— **{summary['agent_recovery_rate']:.0f}%** recovered, automatically."
    )

    st.write("")
    m1, m2, m3 = st.columns(3)
    m1.metric("Transactions handled", summary["n_transactions"])
    m2.metric("Currently in progress", int((results["agent_action"] != "STOP").sum()) - int(results["agent_resolved"].sum()),
               help="Retries, nudges, and escalations still working toward recovery")
    m3.metric("Sent to a human for review", int((results["agent_action"] == "ESCALATE_HUMAN").sum()))

    st.write("")
    st.markdown("#### Your top reasons for lost revenue right now")
    top_reasons = (
        results.groupby("failure_reason")["amount"].sum().sort_values(ascending=False).head(5).reset_index()
    )
    top_reasons["failure_reason"] = top_reasons["failure_reason"].str.replace("_", " ")
    fig3 = go.Figure(go.Bar(
        x=top_reasons["amount"], y=top_reasons["failure_reason"], orientation="h",
        marker_color=ORANGE, hovertemplate="₹%{x:,.0f} at risk<extra></extra>",
    ))
    fig3.update_layout(
        height=260, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, font=dict(color=INK_PRIMARY),
        xaxis=dict(title="₹ at risk", gridcolor=GRID, zeroline=False),
        yaxis=dict(title="", categoryorder="total ascending"),
    )
    st.plotly_chart(fig3, width="stretch")

    if systemic_issues:
        st.write("")
        with st.container(border=True):
            st.markdown("#### ⚠️ Heads up")
            for issue in systemic_issues.values():
                phrase = SYSTEMIC_REASON_PHRASE.get(issue.failure_reason, issue.failure_reason.replace("_", " "))
                st.markdown(
                    f"Your **{issue.payment_method}** payments are **{phrase}** more than usual right now "
                    f"({issue.ratio:.0f}x normal) — this looks like a bank/gateway issue, not your customers. "
                    f"We've paused retries for these and alerted your ops team so nobody gets spammed during the outage."
                )
