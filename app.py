"""
Recovery Copilot dashboard — Streamlit frontend over the Python agent
pipeline. Run with:

    streamlit run app.py
"""
from __future__ import annotations

import os
import random
import re
import tempfile

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

# --- plain-language labels for everything the underlying code calls by its
# internal name -- an end user should never see SEND_MESSAGE, cat__..., etc.
ACTION_LABEL = {
    "SEND_MESSAGE": "Sent a reminder",
    "RETRY_PAYMENT": "Retried the payment",
    "ESCALATE_HUMAN": "Sent to a specialist",
    "ESCALATE_COLLECTIONS": "Sent to collections/legal",
    "ESCALATE_OPS": "Flagged as a system issue",
    "STOP": "Left alone (not worth pursuing)",
}
RISK_TYPE_LABEL = {
    "payment_failure": "Payment failure",
    "checkout_abandonment": "Checkout drop-off",
    "subscription_failure": "Subscription failure",
    "invoice_overdue": "Overdue invoice",
}
# a distinct phrase per systemic-issue reason -- otherwise two different
# netbanking issues (e.g. timeouts vs mandate errors) both read as
# "netbanking payments are failing" with just a different number, which
# looks like the same fact contradicting itself
SYSTEMIC_REASON_PHRASE = {
    "bank_timeout": "timing out",
    "network_drop": "dropping mid-payment",
    "mandate_bank_error": "erroring on auto-pay charges",
    "issuer_declined": "being declined by the bank",
}
_NUMERIC_FEATURE_LABEL = {
    "previous_attempts": "how many times we've already tried",
    "amount_log": "the transaction amount",
    "days_since_event": "how long ago this happened",
    "customer_local_hour": "time of day",
    "do_not_contact_flag": "contact preference",
}
_CATEGORICAL_PREFIX_LABEL = {
    "risk_type_": "issue type",
    "failure_reason_": "reason",
    "payment_method_": "payment method",
    "customer_segment_": "customer type",
}


def _friendly_feature(feat: str) -> str:
    """Translates a raw model feature name (e.g. cat__customer_segment_vip)
    into something a person would read, without inventing anything --
    every word here is derived from the real feature name."""
    name = feat.split("__", 1)[-1] if "__" in feat else feat
    if name in _NUMERIC_FEATURE_LABEL:
        return _NUMERIC_FEATURE_LABEL[name]
    for prefix, label in _CATEGORICAL_PREFIX_LABEL.items():
        if name.startswith(prefix):
            value = name[len(prefix):].replace("_", " ")
            return f"{label}: {value}"
    return name.replace("_", " ")


def _strength(contrib: float) -> str:
    a = abs(contrib)
    if a >= 0.35:
        return "a strong"
    if a >= 0.15:
        return "a moderate"
    return "a slight"


def render_explanation(row: pd.Series, model) -> None:
    st.markdown("**Why we think this:**")
    for feat, contrib in model.explain(row, top_k=3):
        arrow = "↑" if contrib > 0 else "↓"
        verb = "improves" if contrib > 0 else "hurts"
        st.markdown(f"- {arrow} **{_friendly_feature(feat)}** — {_strength(contrib)} factor that {verb} the chances of recovery")


def humanize(text: str) -> str:
    return text.replace("_", " ").strip().capitalize()


def display_reasoning(text: str) -> str:
    """Lightly cleans up a policy-engine reasoning string for the primary,
    end-user-facing view -- the underlying text stays precise (it's also
    the audit-trail record, so it should), this just smooths the bits that
    read as internal jargon: a raw score becomes a percentage, quoted
    internal identifiers and snake_case tokens get their underscores
    turned into spaces. Nothing about the content changes, only the surface
    text -- the full, unmodified original is still in Technical details."""
    text = re.sub(
        r"[Rr]ecoverability score \(?(\d+\.\d+)\)?",
        lambda m: f"Confidence ({float(m.group(1)) * 100:.0f}%)",
        text,
    )
    text = re.sub(r"'([a-z0-9_]+)'", lambda m: m.group(1).replace("_", " "), text)
    text = re.sub(r"\b([a-z]+_[a-z_]+)\b", lambda m: m.group(1).replace("_", " "), text)
    return text


st.set_page_config(page_title="Recovery Copilot", page_icon="\U0001F4B8", layout="wide")

st.markdown(
    """<style>
    div[data-testid="stMetric"] { background: #f9f9f7; border: 1px solid #e1e0d9; border-radius: 10px; padding: 14px 16px; }
    div[data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 600; }
    div[data-testid="stMetricLabel"] { color: #52514e; }
    h1, h2, h3 { letter-spacing: -0.01em; }
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="Setting things up...")
def get_model():
    return train_default_model()


@st.cache_data(show_spinner="Loading your transactions...")
def get_run(seed: int):
    df = generate(seed=seed)
    model = get_model()
    results, summary, _, systemic_issues = run_pipeline(df, model=model)
    return df, results, summary, systemic_issues


@st.cache_data(show_spinner="Simulating the recovery timeline...")
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
st.sidebar.caption("Automatic payment recovery")

if "seed" not in st.session_state:
    st.session_state["seed"] = 42
if st.sidebar.button("\U0001F504 Load a new sample", width="stretch"):
    st.session_state["seed"] = random.randint(1, 9999)

seed = st.sidebar.number_input(
    "Sample dataset", min_value=1, max_value=9999, step=1, key="seed",
    help="This demo runs on simulated transactions — switch the number to preview a different batch.",
)

with st.sidebar.expander("ℹ️ About Recovery Copilot"):
    st.markdown(
        "Recovery Copilot automatically detects payment issues — failed "
        "payments, abandoned checkouts, failed subscriptions, and overdue "
        "invoices — figures out the most likely reason, and takes the "
        "right action to recover the money: a retry, a personalized "
        "reminder, or handing it to a specialist when that's the better call.\n\n"
        "Every decision is logged, so you can always see exactly what "
        "happened and why."
    )

df, results, summary, systemic_issues = get_run(int(seed))
audit = AuditTrail()
model = get_model()

st.title("\U0001F4B8 Recovery Copilot")
st.caption("Automatically recovers failed payments, abandoned checkouts, and overdue invoices — see exactly what happened and why.")

tab_dashboard, tab_transactions, tab_timeline, tab_try, tab_live = st.tabs(
    ["\U0001F3E0 Dashboard", "\U0001F4CB Transactions", "\U0001F5D3️ Recovery timeline",
     "\U0001F9EA Try a transaction", "\U0001F534 Live"]
)

# =============================================================== DASHBOARD ==
with tab_dashboard:
    st.markdown(f"## This period, Recovery Copilot recovered **₹{summary['agent_net_recovered']:,.0f}** for you")
    st.markdown(
        f"out of ₹{summary['total_at_risk']:,.0f} at risk across {summary['n_transactions']} transactions — "
        f"**{summary['agent_recovery_rate']:.0f}%** recovered, automatically."
    )

    st.write("")

    with st.container(border=True):
        if systemic_issues:
            st.markdown(f"#### ⚠️ Heads up")
            for issue in systemic_issues.values():
                phrase = SYSTEMIC_REASON_PHRASE.get(issue.failure_reason, humanize(issue.failure_reason).lower())
                st.markdown(
                    f"Your **{issue.payment_method}** payments are **{phrase}** more than usual right now "
                    f"({issue.ratio:.0f}x normal) — this looks like a bank/gateway issue, not your customers. "
                    f"We've paused retries for these and alerted your ops team so nobody gets contacted "
                    f"unnecessarily during the outage."
                )
        else:
            st.markdown("#### ✅ Everything looks normal")
            st.caption("No unusual payment patterns detected right now.")

    st.write("")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total at risk", f"₹{summary['total_at_risk']:,.0f}")
    k2.metric(
        "Recovered", f"₹{summary['agent_net_recovered']:,.0f}",
        delta=f"+₹{summary['net_uplift_amount']:,.0f} vs. before",
        help="After accounting for the cost of recovering it — an SMS, a call, a specialist's time.",
    )
    k3.metric("Recovery rate", f"{summary['agent_recovery_rate']:.0f}%")
    in_progress = int((results["agent_action"] != "STOP").sum()) - int(results["agent_resolved"].sum())
    k4.metric("Currently in progress", in_progress, help="Retries, reminders, and escalations still working toward recovery")

    st.caption(
        f"This also means **{summary['baseline_compliance_violations_avoided']}** customers were protected from "
        f"unnecessary contact, and **{summary['promises_kept']} of {summary['promises_kept'] + summary['promises_broken']}** "
        f"payment promises were kept — the ones that weren't got automatically sent to a specialist, not dropped."
    )

    st.write("")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.subheader("Recovered, by category")
        agg = (
            results.groupby("risk_type")[["baseline_recovered_amount", "agent_recovered_amount"]]
            .sum().reset_index()
        )
        agg["risk_label"] = agg["risk_type"].map(RISK_TYPE_LABEL).fillna(agg["risk_type"])
        agg = agg.sort_values("agent_recovered_amount")

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=agg["risk_label"], x=agg["baseline_recovered_amount"], orientation="h",
            name="A simple retry-everyone approach", marker_color=BLUE_LIGHT,
            hovertemplate="₹%{x:,.0f}<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            y=agg["risk_label"], x=agg["agent_recovered_amount"], orientation="h",
            name="Recovery Copilot", marker_color=BLUE,
            hovertemplate="₹%{x:,.0f}<extra></extra>",
        ))
        fig.update_layout(
            barmode="group", height=300, margin=dict(l=10, r=10, t=10, b=10),
            plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, font=dict(color=INK_PRIMARY),
            xaxis=dict(title="Recovered amount (₹)", gridcolor=GRID, zeroline=False),
            yaxis=dict(title=""),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        st.plotly_chart(fig, width="stretch")

    with c2:
        st.subheader("What's happening")
        action_counts = results["agent_action"].value_counts()
        action_labels = [ACTION_LABEL.get(a, a) for a in action_counts.index]

        fig2 = go.Figure(go.Bar(
            x=action_counts.values, y=action_labels, orientation="h",
            marker_color=BLUE, customdata=action_counts.index,
            hovertemplate="%{y}: %{x}<extra></extra>",
        ))
        fig2.update_layout(
            height=300, margin=dict(l=10, r=10, t=10, b=10),
            plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, font=dict(color=INK_PRIMARY),
            xaxis=dict(title="Transactions", gridcolor=GRID, zeroline=False),
            yaxis=dict(title="", categoryorder="total ascending"),
        )
        event = st.plotly_chart(fig2, width="stretch", on_select="rerun", key="action_chart", selection_mode="points")

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
            f"**Example — {ACTION_LABEL.get(clicked_action, clicked_action)}:** a "
            f"₹{example['amount']:,.0f} {RISK_TYPE_LABEL.get(example['risk_type'], example['risk_type']).lower()} case. "
            f"Look it up on the **Transactions** tab (ID `{example['transaction_id']}`) for the full story."
        )
    else:
        st.caption("Click a bar to see a real example of that decision.")

    st.write("")
    st.subheader("Where you're losing the most money right now")
    top_reasons = (
        results.groupby("failure_reason")["amount"].sum().sort_values(ascending=False).head(5).reset_index()
    )
    top_reasons["failure_reason"] = top_reasons["failure_reason"].apply(humanize)
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

# ============================================================ TRANSACTIONS ==
with tab_transactions:
    st.subheader("All transactions")
    st.caption("Every payment issue Recovery Copilot has handled this period, and what it did about each one.")

    f1, f2, f3 = st.columns(3)
    risk_filter = f1.multiselect("Issue type", sorted(results["risk_type"].unique()),
                                  format_func=lambda x: RISK_TYPE_LABEL.get(x, x))
    action_filter = f2.multiselect("Status", sorted(results["agent_action"].unique()),
                                    format_func=lambda x: ACTION_LABEL.get(x, x))
    segment_filter = f3.multiselect("Customer type", sorted(results["customer_segment"].unique()),
                                     format_func=lambda x: x.capitalize())

    view = results.copy()
    if risk_filter:
        view = view[view["risk_type"].isin(risk_filter)]
    if action_filter:
        view = view[view["agent_action"].isin(action_filter)]
    if segment_filter:
        view = view[view["customer_segment"].isin(segment_filter)]

    display_df = view.sort_values("recoverability_score", ascending=False)[[
        "transaction_id", "risk_type", "failure_reason", "amount", "customer_segment",
        "recoverability_score", "agent_action", "agent_resolved", "agent_recovered_amount",
    ]].copy()
    display_df["risk_type"] = display_df["risk_type"].map(RISK_TYPE_LABEL)
    display_df["failure_reason"] = display_df["failure_reason"].apply(humanize)
    display_df["customer_segment"] = display_df["customer_segment"].str.capitalize()
    display_df["recoverability_score"] = (display_df["recoverability_score"] * 100).round(0).astype(int).astype(str) + "%"
    display_df["agent_action"] = display_df["agent_action"].map(ACTION_LABEL)
    display_df["agent_resolved"] = display_df["agent_resolved"].map({True: "✅ Recovered", False: "In progress / not yet"})
    display_df.columns = [
        "Transaction", "Issue Type", "Reason", "Amount (₹)", "Customer Type",
        "Confidence", "Action Taken", "Result", "Recovered (₹)",
    ]
    st.dataframe(display_df, width="stretch", height=280, hide_index=True)

    st.divider()

    st.subheader("Look up a transaction")
    txn_id = st.selectbox("Transaction ID", view["transaction_id"].tolist() if not view.empty else results["transaction_id"].tolist())

    if txn_id:
        row = df[df["transaction_id"] == txn_id].iloc[0]
        res_row = results[results["transaction_id"] == txn_id].iloc[0]
        decision = decide(row, float(res_row["recoverability_score"]), systemic_issues)

        d1, d2 = st.columns([1, 1])
        with d1:
            with st.container(border=True):
                st.markdown(f"**Customer:** {row['customer_name']} ({row['customer_segment']})")
                st.markdown(f"**Amount:** ₹{row['amount']:,.0f} · **Issue:** {RISK_TYPE_LABEL.get(row['risk_type'], row['risk_type'])}")
                st.markdown(f"**Reason:** {humanize(row['failure_reason'])}")
                st.markdown(f"**Recovery Copilot's confidence:** {res_row['recoverability_score'] * 100:.0f}%")
                render_explanation(row, model)

        with d2:
            with st.container(border=True):
                st.markdown(f"**What we did:** {ACTION_LABEL.get(decision.action, decision.action)}"
                            + (f" via {decision.channel.replace('_', ' ')}" if decision.channel else ""))
                st.markdown(f"**Estimated cost:** ₹{res_row['agent_intervention_cost']:.2f}")
                st.markdown("**Why:**")
                for r in decision.reasoning:
                    st.markdown(f"- {display_reasoning(r)}")

                if res_row["promise_to_pay_status"] in ("kept", "broken"):
                    icon = "✅" if res_row["promise_to_pay_status"] == "kept" else "🚨"
                    st.markdown(f"**Promise to pay:** {icon} {res_row['promise_to_pay_note']}")

                if decision.action == "SEND_MESSAGE":
                    msg = generate_message(row, decision)
                    st.markdown("**Message sent to the customer:**")
                    st.info(msg)
                    if decision.channel == "voice_hinglish":
                        if st.button("\U0001F50A Play the voice message"):
                            with tempfile.TemporaryDirectory() as tmp:
                                out_path = os.path.join(tmp, "message.wav")
                                ok = synthesize_voice(msg, out_path)
                                if ok:
                                    with open(out_path, "rb") as f:
                                        st.audio(f.read(), format="audio/wav")
                                else:
                                    st.warning("Voice playback isn't available in this environment — message text shown above.")

        with st.expander("\U0001F527 Technical details"):
            st.caption("The underlying model output, API mapping, and full audit log for this transaction.")
            st.markdown("**Raw model feature contributions:**")
            for feat, contrib in model.explain(row):
                direction = "increases" if contrib > 0 else "decreases"
                st.markdown(f"- `{feat}` — {direction} recoverability ({contrib:+.2f})")

            razorpay_call = build_call(row, decision)
            if razorpay_call is not None:
                st.markdown("**Razorpay API call this would trigger:**")
                st.code(f"{razorpay_call.method} {razorpay_call.path}", language="text")
                st.json(razorpay_call.payload)
                st.caption(razorpay_call.note)

            st.markdown("**Full audit trail:**")
            trail = audit.for_transaction(txn_id)
            if not trail.empty:
                st.dataframe(trail[["timestamp", "action", "reasoning", "stopping_rule_triggered", "systemic_issue_note"]], width="stretch")
            else:
                st.caption("No audit entries found — reload the sample to regenerate the log.")

# ================================================================ TIMELINE ==
with tab_timeline:
    st.subheader("Recovery over time")
    st.caption(
        "The Dashboard shows one snapshot. This shows what happens over several days as "
        "Recovery Copilot follows up — retries, reminders, and escalations — until each "
        "case is resolved, or we stop for a good reason."
    )
    n_days = st.slider("Number of days to simulate", min_value=2, max_value=10, value=5)
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
        xaxis=dict(title="Day", gridcolor=GRID, zeroline=False, dtick=1),
        yaxis=dict(title="Total recovered (₹)", gridcolor=GRID),
        showlegend=False,
    )
    st.plotly_chart(wf_fig, width="stretch")

    last_day = daily.iloc[-1]
    with st.container(border=True):
        st.markdown(
            f"By day **{int(last_day['day'])}**: **{int(last_day['cumulative_resolved'])}** of "
            f"{len(df)} transactions resolved, **₹{last_day['cumulative_recovered']:,.0f}** recovered — "
            f"more than a single snapshot shows, because following up gives every case "
            f"multiple chances to resolve, not just one."
        )
    with st.expander("Day-by-day breakdown"):
        daily_display = daily.rename(columns={
            "day": "Day", "resolved_today": "Resolved that day", "recovered_today": "Recovered that day (₹)",
            "cumulative_resolved": "Total resolved so far", "cumulative_recovered": "Total recovered so far (₹)",
        })
        st.dataframe(daily_display, width="stretch", hide_index=True)

# ===================================================================== TRY ==
with tab_try:
    st.subheader("See how Recovery Copilot handles a case")
    st.caption("Fill in the details below and watch Recovery Copilot decide what to do — instantly, on whatever you enter.")

    lc1, lc2, lc3 = st.columns(3)
    with lc1:
        live_risk_type = st.selectbox("Issue type", RISK_TYPES, format_func=lambda x: RISK_TYPE_LABEL.get(x, x), key="live_risk_type")
        live_failure_reason = st.selectbox("Reason", FAILURE_REASONS[live_risk_type], format_func=humanize, key="live_failure_reason")
        live_amount = st.number_input("Amount (₹)", min_value=50.0, max_value=250000.0, value=5000.0, step=50.0, key="live_amount")
    with lc2:
        live_payment_method = st.selectbox("Payment method", PAYMENT_METHODS, format_func=lambda x: x.capitalize(), key="live_payment_method")
        live_segment = st.selectbox("Customer type", CUSTOMER_SEGMENTS, index=1, format_func=lambda x: x.capitalize(), key="live_segment")
        live_attempts = st.slider("Times already tried", 0, 4, 0, key="live_attempts")
    with lc3:
        live_hour = st.slider("Customer's local time (hour)", 0, 23, 12, key="live_hour")
        live_dnc = st.checkbox("Customer has opted out of contact", key="live_dnc")
        st.caption("Tip: try 3+ attempts to see it stop on its own, a very high amount to see it "
                   "go straight to a specialist, or an overdue invoice above ₹15,000 at 45+ days "
                   "to see it go to collections/legal.")

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
            st.markdown(f"### Confidence: **{live_score * 100:.0f}%**")
            st.progress(min(max(live_score, 0.0), 1.0))
            render_explanation(live_row, model)

    with r2:
        with st.container(border=True):
            action_color = STATUS_CRITICAL if live_decision.action == "STOP" else STATUS_GOOD
            action_text = ACTION_LABEL.get(live_decision.action, live_decision.action)
            via_text = f" via {live_decision.channel.replace('_', ' ')}" if live_decision.channel else ""
            heading_html = f'### <span style="color:{action_color}">{action_text}</span>{via_text}'
            st.markdown(heading_html, unsafe_allow_html=True)
            st.markdown(f"**Estimated cost:** ₹{estimate_cost(live_decision):.2f}")
            st.markdown("**Why:**")
            for r in live_decision.reasoning:
                st.markdown(f"- {display_reasoning(r)}")

    if live_decision.action == "SEND_MESSAGE":
        st.markdown("**Message that would be sent:**")
        st.info(generate_message(live_row, live_decision))

    with st.expander("\U0001F527 Technical details"):
        if live_decision.retry_method:
            st.markdown(f"**Retry sequencer:** `{live_decision.retry_method}` method, in {live_decision.retry_delay_hours}h")
        st.markdown("**Raw model feature contributions:**")
        for feat, contrib in model.explain(live_row):
            direction = "increases" if contrib > 0 else "decreases"
            st.markdown(f"- `{feat}` — {direction} recoverability ({contrib:+.2f})")

        live_call = build_call(live_row, live_decision)
        if live_call is not None:
            st.markdown("**Razorpay API call this would trigger:**")
            st.code(f"{live_call.method} {live_call.path}", language="text")
            st.json(live_call.payload)
            st.caption(live_call.note)

# ==================================================================== LIVE ==
with tab_live:
    st.subheader("Real payments, real time")
    st.caption(
        "Everything above runs on a simulated batch, so the numbers are reproducible for a demo. "
        "This tab is different: it shows actual payment failures from a connected Razorpay account, "
        "the moment Razorpay reports them — scored and decided by the same engine, with no human "
        "involved in between."
    )

    if st.button("\U0001F504 Refresh", key="live_refresh"):
        st.rerun()

    live_audit = AuditTrail(path="data/live_audit_log.jsonl")
    live_df = live_audit.load_all()

    if live_df.empty:
        st.info(
            "No real transactions yet. Start the API service (`uvicorn api:app`), open **/checkout** "
            "in a browser with a Razorpay Test Mode account connected, and pay with one of "
            "[Razorpay's test failure cards](https://razorpay.com/docs/payments/payments/test-card-details/). "
            "See `pitch/razorpay_live_setup.md` for the full setup."
        )
    else:
        live_df = live_df.sort_values("timestamp", ascending=False).reset_index(drop=True)

        lk1, lk2, lk3 = st.columns(3)
        lk1.metric("Real transactions handled", len(live_df))
        lk2.metric("Total amount involved", f"₹{live_df['amount'].sum():,.0f}")
        most_common_action = live_df["action"].mode().iat[0] if not live_df["action"].mode().empty else "—"
        lk3.metric("Most common response", ACTION_LABEL.get(most_common_action, most_common_action))

        st.write("")
        def field(entry, key, default=""):
            """entry.get(key, default) but also treats NaN as missing --
            older log lines predate a field (e.g. customer_segment was
            added after the first few real entries), which pandas
            represents as NaN rather than a missing key."""
            val = entry.get(key, default)
            return default if (val is None or (isinstance(val, float) and pd.isna(val))) else val

        for _, entry in live_df.iterrows():
            action = field(entry, "action")
            ts_raw = field(entry, "timestamp")
            try:
                ts = pd.Timestamp(ts_raw).strftime("%b %d, %H:%M:%S UTC") if ts_raw else ""
            except (ValueError, TypeError):
                ts = str(ts_raw)
            with st.container(border=True):
                h1, h2 = st.columns([3, 1])
                with h1:
                    action_color = STATUS_CRITICAL if action == "STOP" else STATUS_GOOD
                    segment = field(entry, "customer_segment", "unknown")
                    st.markdown(
                        f"**₹{field(entry, 'amount', 0):,.0f}** · "
                        f"{humanize(str(field(entry, 'failure_reason')))} · "
                        f"{str(segment).capitalize()} customer &nbsp; "
                        f'→ <span style="color:{action_color}">**{ACTION_LABEL.get(action, action)}**</span>',
                        unsafe_allow_html=True,
                    )
                    score = field(entry, "recoverability_score", None)
                    if score is not None:
                        st.caption(f"Confidence: {float(score) * 100:.0f}%")
                with h2:
                    st.caption(ts)
                    st.caption(f"`{field(entry, 'transaction_id')}`")

                reasoning = field(entry, "reasoning", None)
                if isinstance(reasoning, list) and reasoning:
                    st.markdown("**Why:**")
                    for r in reasoning:
                        st.markdown(f"- {display_reasoning(str(r))}")

                with st.expander("\U0001F527 Technical details"):
                    st.markdown(f"**Event:** `{field(entry, 'event')}` from Razorpay's webhook")
                    st.markdown(
                        f"**Raw Razorpay error:** `{field(entry, 'raw_error_reason', '—')}` / "
                        f"`{field(entry, 'raw_error_code', '—')}` — {field(entry, 'raw_error_description', '—')}"
                    )
                    st.caption(
                        "Razorpay Test Mode reports the same generic reason for every simulated failure "
                        "type — see agent/razorpay_live.py for what's been verified about this."
                    )
