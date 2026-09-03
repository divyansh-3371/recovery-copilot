"""
Illustrative mapping from each bounded agent action to Razorpay's actual API
surface -- shows how Recovery Copilot would plug into a real merchant's
Razorpay integration, rather than only ever operating on synthetic data in
the abstract.

These are STUBS: no live network calls, no credentials, no side effects.
Endpoint paths, payload shapes, and webhook event names follow Razorpay's
public API documentation as understood at build time -- verify against the
current docs before wiring up real credentials. API surfaces evolve, and
the point of this module is to demonstrate integration *shape* (which
product, which call, why), not to be copy-pasted into production untested.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from agent.policy import Decision

# --- inbound: the real-world triggers this agent would consume in place of
# the synthetic batch generator -- Razorpay webhook events, mapped to the
# risk_type each one would populate.
WEBHOOK_EVENT_TO_RISK_TYPE = {
    "payment.failed": "payment_failure",
    "subscription.pending": "subscription_failure",   # mandate due, charge not yet captured
    "subscription.halted": "subscription_failure",     # mandate retries exhausted on Razorpay's side
    "invoice.expired": "invoice_overdue",
    # a resolving signal, not a new risk -- used to mark a tracked transaction
    # resolved rather than open a new one:
    "order.paid": None,
}


@dataclass(frozen=True)
class RazorpayCallStub:
    """Describes the API call a decision WOULD make in production -- method,
    path, and payload shape -- without making it."""
    method: str
    path: str
    payload: dict
    note: str


def build_call(row: pd.Series, decision: Decision) -> RazorpayCallStub | None:
    """Returns the Razorpay call stub for a Decision, or None for actions
    that route internally rather than calling a Razorpay API (STOP,
    ESCALATE_HUMAN has no gateway call of its own -- it hands off to a
    human agent's existing tooling)."""

    if decision.action == "RETRY_PAYMENT":
        if row["risk_type"] == "subscription_failure":
            return RazorpayCallStub(
                method="POST",
                path="/v1/payment_links",
                payload={
                    "amount": int(row["amount"] * 100), "currency": row["currency"],
                    "customer": {"name": row.get("customer_name", ""), "contact": ""},
                    "reference_id": f"mandate-retry-{row['transaction_id']}",
                    "notify": {"sms": True, "email": True},
                },
                note=("Razorpay's Subscriptions API schedules charges on the mandate's own "
                      "cycle rather than exposing a manual off-cycle retry call; in practice "
                      "this step re-presents the charge via a fresh Payment Link against the "
                      "subscription amount instead."),
            )
        return RazorpayCallStub(
            method="POST",
            path="/v1/orders",
            payload={"amount": int(row["amount"] * 100), "currency": row["currency"],
                     "notes": {"retry_of_payment_id": row["transaction_id"], "attempt": row["previous_attempts"] + 1}},
            note=("Razorpay's own smart routing already retries many transient gateway-level "
                  "failures automatically; this action targets the cases beyond that -- "
                  "scheduling a fresh checkout attempt against a new Order at the delay this "
                  "agent decided, once the transient condition has likely cleared."),
        )

    if decision.action == "SEND_MESSAGE":
        return RazorpayCallStub(
            method="POST",
            path="/v1/payment_links",
            payload={
                "amount": int(row["amount"] * 100), "currency": row["currency"],
                "customer": {"name": row.get("customer_name", "")},
                "notify": {
                    "sms": decision.channel in ("sms", "whatsapp", "voice_hinglish"),
                    "email": decision.channel == "email",
                },
                "notes": {"channel": decision.channel, "reason": row["failure_reason"]},
            },
            note="Payment Links API create + notify -- supports resend-by-SMS/email natively; "
                 "voice_hinglish is layered on top via this project's own TTS, not a Razorpay API.",
        )

    if decision.action == "ESCALATE_OPS":
        return RazorpayCallStub(
            method="internal",
            path="ops-alerting-channel",
            payload={"systemic_issue": decision.systemic_issue_note},
            note="Not a Razorpay API call -- routes to the merchant's own ops/on-call tooling "
                 "(e.g. a Slack or PagerDuty webhook), since the fix here is operational, not "
                 "a payment retry.",
        )

    return None
