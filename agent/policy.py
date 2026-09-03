"""
Decision engine: turns a recoverability score + transaction context into one
bounded action. This is the module that answers the buildathon's "compliant
escalation procedures with stopping rules" bar -- every stopping rule below
is checked *before* any customer-facing action is chosen, and every decision
carries an explicit, logged reason.

Actions (bounded — the agent can only ever pick one of these five):
  RETRY_PAYMENT   - reattempt the payment automatically (no customer contact)
  SEND_MESSAGE     - a personalized nudge to the customer, on a chosen channel
  ESCALATE_HUMAN   - hand off to a human recovery agent (high value / low confidence)
  ESCALATE_OPS     - a systemic/infra issue was detected; alert ops, don't blame the customer
  STOP             - do nothing further on this transaction, with a compliance reason
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from agent.retry_sequencer import next_step as next_retry_step
from agent.root_cause import SystemicIssue

HIGH_SCORE = 0.60
LOW_SCORE = 0.35
MIN_ECONOMICAL_AMOUNT = 150.0
HIGH_VALUE_AMOUNT = 20000.0
MAX_ATTEMPTS = 3
QUIET_HOURS = set(range(22, 24)) | set(range(0, 8))

CARD_UPDATE_REASONS = {"card_expired", "wrong_cvv"}
MANDATE_REASONS = {"mandate_expired", "mandate_insufficient_funds", "mandate_bank_error"}


@dataclass
class Decision:
    transaction_id: str
    action: str
    channel: str | None = None
    retry_delay_hours: float | None = None
    retry_method: str | None = None
    scheduled_hour: int | None = None
    stopping_rule_triggered: str | None = None
    systemic_issue_note: str | None = None
    reasoning: list[str] = field(default_factory=list)
    recoverability_score: float = 0.0


def _choose_channel(row: pd.Series, score: float) -> str:
    if row["customer_segment"] == "vip":
        return "voice_call"
    if row["risk_type"] == "invoice_overdue":
        return "email"
    # showcase the Hinglish voice-recovery direction for returning/vip customers
    # who've already missed one attempt -- a phone-style nudge outperforms a text
    if row["previous_attempts"] >= 1 and row["customer_segment"] in ("returning", "vip"):
        return "voice_hinglish"
    if row["payment_method"] == "upi":
        return "whatsapp"
    return "sms"


def decide(row: pd.Series, score: float, systemic_issues: dict[tuple[str, str], SystemicIssue]) -> Decision:
    d = Decision(transaction_id=row["transaction_id"], action="STOP", recoverability_score=score)

    # --- stopping rules, checked first, in priority order -------------------
    if row["do_not_contact"]:
        d.stopping_rule_triggered = "do_not_contact"
        d.reasoning.append("Customer is marked do-not-contact — no outreach permitted (compliance).")
        return d

    if row["previous_attempts"] >= MAX_ATTEMPTS:
        d.stopping_rule_triggered = "max_attempts_reached"
        d.reasoning.append(f"Already at {row['previous_attempts']} attempts — cap of {MAX_ATTEMPTS} reached, stopping.")
        return d

    if row["amount"] < MIN_ECONOMICAL_AMOUNT and row["customer_segment"] != "vip":
        d.stopping_rule_triggered = "uneconomical_amount"
        d.reasoning.append(f"Amount ₹{row['amount']:.0f} is below the ₹{MIN_ECONOMICAL_AMOUNT:.0f} recovery-cost floor.")
        return d

    # --- systemic / root-cause check ----------------------------------------
    issue_key = (row["payment_method"], row["failure_reason"])
    if issue_key in systemic_issues:
        issue = systemic_issues[issue_key]
        d.action = "ESCALATE_OPS"
        d.systemic_issue_note = issue.note
        d.reasoning.append(issue.note)
        d.reasoning.append("Skipping customer-facing retry/message until infra issue clears (avoids blaming the customer).")
        return d

    # --- card needs updating: never blind-retry, always ask the customer ---
    if row["failure_reason"] in CARD_UPDATE_REASONS and row["risk_type"] == "payment_failure":
        d.action = "SEND_MESSAGE"
        d.channel = _choose_channel(row, score)
        d.reasoning.append(f"Failure reason '{row['failure_reason']}' needs the customer to act — retrying blindly would fail again.")

    # --- mandate retry sequencer: subscription/mandate failures follow an
    # explicit multi-step sequence rather than a single blind re-presentment
    elif score >= HIGH_SCORE and row["risk_type"] == "subscription_failure" and row["failure_reason"] in MANDATE_REASONS:
        step = next_retry_step(row["previous_attempts"], is_mandate=True)
        if step is None:
            d.stopping_rule_triggered = "retry_sequence_exhausted"
            d.reasoning.append("Mandate retry sequence exhausted with no success — stopping rather than retrying indefinitely.")
            return d
        if step.method == "manual_link":
            d.action = "SEND_MESSAGE"
            d.channel = _choose_channel(row, score)
        else:
            d.action = "RETRY_PAYMENT"
            d.retry_delay_hours = step.delay_hours
            d.retry_method = step.method
        d.reasoning.append(f"Mandate retry sequencer, step {step.step}: {step.note}")

    # --- score-driven routing ------------------------------------------------
    elif score >= HIGH_SCORE and row["risk_type"] == "payment_failure":
        step = next_retry_step(row["previous_attempts"], is_mandate=False)
        if step is None:
            d.stopping_rule_triggered = "retry_sequence_exhausted"
            d.reasoning.append("Payment retry sequence exhausted with no success — stopping rather than retrying indefinitely.")
            return d
        d.action = "RETRY_PAYMENT"
        d.retry_delay_hours = step.delay_hours
        d.retry_method = step.method
        d.reasoning.append(f"Retry sequencer, step {step.step}: {step.note}")

    elif score >= HIGH_SCORE or (LOW_SCORE <= score < HIGH_SCORE):
        d.action = "SEND_MESSAGE"
        d.channel = _choose_channel(row, score)
        d.reasoning.append(f"Recoverability score {score:.2f} — a personalized nudge on {d.channel} is the right-cost intervention.")

    elif score < LOW_SCORE and (row["customer_segment"] == "vip" or row["amount"] >= HIGH_VALUE_AMOUNT):
        d.action = "ESCALATE_HUMAN"
        d.reasoning.append(f"Low model confidence ({score:.2f}) but high value (₹{row['amount']:.0f}/{row['customer_segment']}) — worth a human recovery agent.")

    else:
        d.stopping_rule_triggered = "low_confidence_low_value"
        d.reasoning.append(f"Low recoverability score ({score:.2f}) and low value — not worth pursuing further.")
        return d

    # --- quiet-hours compliance note (applies to any customer contact) ------
    if d.action in ("SEND_MESSAGE",) and row["customer_local_hour"] in QUIET_HOURS:
        d.scheduled_hour = 9
        d.reasoning.append(f"Customer local hour is {row['customer_local_hour']}:00 (quiet hours) — deferring send to 09:00.")

    return d
