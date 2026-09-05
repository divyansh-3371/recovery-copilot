"""
Decision engine: turns a recoverability score + transaction context into one
bounded action. This is the module that answers the buildathon's "compliant
escalation procedures with stopping rules" bar -- every stopping rule below
is checked *before* any customer-facing action is chosen, and every decision
carries an explicit, logged reason.

Actions (bounded — the agent can only ever pick one of these six):
  RETRY_PAYMENT       - reattempt the payment automatically (no customer contact)
  SEND_MESSAGE         - a personalized nudge to the customer, on a chosen channel
  ESCALATE_HUMAN       - hand off to a human recovery agent (high value / low confidence /
                         a risk-engine block that needs manual review)
  ESCALATE_COLLECTIONS - a severely overdue, high-value B2B invoice -- formal
                         collections/legal process, distinct from a recovery
                         agent's outreach (different cost, different tone,
                         different compliance weight)
  ESCALATE_OPS         - a systemic/infra issue was detected; alert ops, don't blame the customer
  STOP                 - do nothing further on this transaction, with a compliance reason

Every failure-reason-specific judgment call here (which reasons need the
customer to act, which are safe to blind-retry, which are a compliance
signal that must never be auto-retried) is looked up from
agent/decision_table.py rather than hardcoded per-file, so adding a new
failure reason means adding one row there, not hunting through this file
and simulator.py and keeping them in sync by hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from agent.decision_table import COMPLIANCE_REVIEW_REASONS, CUSTOMER_ACTION_REASONS, MANDATE_REASONS
from agent.retry_sequencer import next_step as next_retry_step
from agent.root_cause import SystemicIssue

HIGH_SCORE = 0.60
LOW_SCORE = 0.35
MIN_ECONOMICAL_AMOUNT = 150.0
HIGH_VALUE_AMOUNT = 20000.0
MAX_ATTEMPTS = 3
QUIET_HOURS = set(range(22, 24)) | set(range(0, 8))

# Cost-aware value triage: above this amount, a human reviews it regardless
# of what the failure-reason mapping would otherwise pick -- a ₹50 nudge-vs-
# retry decision is fine to leave to a rule; a ₹1,00,000 one is worth the
# ₹150 human-agent cost even if the reason category would normally route to
# an automated channel. Checked after compliance-critical routing (stopping
# rules, systemic-issue/ops routing, risk-block review) so those still win,
# but before every other failure-reason-driven branch.
VALUE_TRIAGE_THRESHOLD = 75_000.0

# A severely overdue invoice above this amount goes to formal
# collections/legal, not a recovery agent's outreach -- checked before the
# generic value-triage catch-all so this more specific, more appropriate
# escalation wins for exactly the case it's meant for. Deliberately lower
# than VALUE_TRIAGE_THRESHOLD: a 45+-day-overdue B2B invoice is already a
# different kind of problem at a lower amount than an ordinary high-value
# payment failure is.
COLLECTIONS_REASON = "invoice_overdue_45plus"
COLLECTIONS_AMOUNT_THRESHOLD = 15_000.0

# kept as an alias -- simulator.py and existing callers refer to this name;
# the actual data now lives in agent/decision_table.py
CARD_UPDATE_REASONS = CUSTOMER_ACTION_REASONS


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


def _exhausted_stop_or_escalate(d: Decision, row: pd.Series, stopping_rule: str, exhausted_note: str) -> Decision:
    """Shared by the max-attempts cap and both retry-sequence-exhausted
    paths: automation running out of budget on a high-value or VIP case
    means automation wasn't enough -- not that recovery is impossible. A
    human might still land it (a payment plan, an alternate method); only
    a lower-stakes case truly stops here."""
    if row["customer_segment"] == "vip" or row["amount"] >= HIGH_VALUE_AMOUNT:
        d.action = "ESCALATE_HUMAN"
        d.reasoning.append(
            f"{exhausted_note} on a ₹{row['amount']:.0f}/{row['customer_segment']} case — "
            f"worth a human where automation didn't land it."
        )
    else:
        d.stopping_rule_triggered = stopping_rule
        d.reasoning.append(f"{exhausted_note} — stopping rather than retrying/messaging indefinitely.")
    return d


def decide(row: pd.Series, score: float, systemic_issues: dict[tuple[str, str], SystemicIssue]) -> Decision:
    d = Decision(transaction_id=row["transaction_id"], action="STOP", recoverability_score=score)

    # --- systemic / root-cause check -- checked before anything
    # customer-specific: detecting and reporting an infrastructure problem
    # is completely orthogonal to any one customer's compliance
    # attributes or this transaction's economics, and (like ESCALATE_OPS
    # itself) never contacts the customer -- so a tiny transaction or a
    # do-not-contact customer failing during a genuine outage must still
    # surface it to ops, not get silently absorbed by an unrelated
    # stopping rule before anyone finds out there's an outage at all. ----
    issue_key = (row["payment_method"], row["failure_reason"])
    if issue_key in systemic_issues:
        issue = systemic_issues[issue_key]
        d.action = "ESCALATE_OPS"
        d.systemic_issue_note = issue.note
        d.reasoning.append(issue.note)
        d.reasoning.append("Skipping customer-facing retry/message until infra issue clears (avoids blaming the customer).")
        return d

    # --- stopping rules, checked next, in priority order --------------------
    if row["do_not_contact"]:
        d.stopping_rule_triggered = "do_not_contact"
        d.reasoning.append("Customer is marked do-not-contact — no outreach permitted (compliance).")
        return d

    if row["previous_attempts"] >= MAX_ATTEMPTS:
        return _exhausted_stop_or_escalate(
            d, row, "max_attempts_reached",
            f"Already at {row['previous_attempts']} attempts (cap {MAX_ATTEMPTS} reached)",
        )

    # Exempts vip (an established relationship worth protecting) and new
    # (the sunk acquisition-cost argument -- same reasoning as the
    # low-score branch further down) -- a returning customer's tiny failed
    # payment is the only case with neither an existing relationship to
    # protect nor a recapture argument for the amount involved.
    if row["amount"] < MIN_ECONOMICAL_AMOUNT and row["customer_segment"] not in ("vip", "new"):
        d.stopping_rule_triggered = "uneconomical_amount"
        d.reasoning.append(f"Amount ₹{row['amount']:.0f} is below the ₹{MIN_ECONOMICAL_AMOUNT:.0f} recovery-cost floor.")
        return d

    # --- risk/fraud-engine block: NEVER auto-retry, always human review ----
    # (auto-retrying past a risk block is itself a compliance risk -- it can
    # look like card-testing/fraud evasion, not legitimate recovery)
    if row["failure_reason"] in COMPLIANCE_REVIEW_REASONS:
        d.action = "ESCALATE_HUMAN"
        d.reasoning.append(
            f"Failure reason '{row['failure_reason']}' is a risk/fraud-engine signal — "
            f"auto-retrying past it would itself be a compliance risk. Routing to human review, no auto-retry, no customer message."
        )

    # --- severely overdue + high-value B2B invoice: formal collections, not
    # a recovery agent's outreach -- more specific than the generic value
    # triage below, so it's checked first ------------------------------------
    elif row["failure_reason"] == COLLECTIONS_REASON and row["amount"] >= COLLECTIONS_AMOUNT_THRESHOLD:
        d.action = "ESCALATE_COLLECTIONS"
        d.reasoning.append(
            f"Invoice is 45+ days overdue at ₹{row['amount']:,.0f} — above the ₹{COLLECTIONS_AMOUNT_THRESHOLD:,.0f} "
            f"threshold for formal collections/legal referral, rather than a recovery agent's outreach."
        )

    # --- cost-aware value triage: too much at stake to leave to the usual
    # failure-reason mapping, regardless of which category it would pick ---
    elif row["amount"] >= VALUE_TRIAGE_THRESHOLD:
        d.action = "ESCALATE_HUMAN"
        d.reasoning.append(
            f"Amount ₹{row['amount']:,.0f} is above the ₹{VALUE_TRIAGE_THRESHOLD:,.0f} value-triage threshold — "
            f"routed to a human regardless of the usual failure-reason mapping (this would otherwise have been "
            f"an automated retry/message for '{row['failure_reason']}'); too much at stake for an automated path alone."
        )

    # --- card needs updating: never blind-retry, always ask the customer ---
    elif row["failure_reason"] in CARD_UPDATE_REASONS and row["risk_type"] == "payment_failure":
        d.action = "SEND_MESSAGE"
        d.channel = _choose_channel(row, score)
        d.reasoning.append(f"Failure reason '{row['failure_reason']}' needs the customer to act — retrying blindly would fail again.")

    # --- mandate retry sequencer: subscription/mandate failures follow an
    # explicit multi-step sequence rather than a single blind re-presentment
    elif score >= HIGH_SCORE and row["risk_type"] == "subscription_failure" and row["failure_reason"] in MANDATE_REASONS:
        step = next_retry_step(row["previous_attempts"], is_mandate=True, failure_reason=row["failure_reason"])
        if step is None:
            return _exhausted_stop_or_escalate(d, row, "retry_sequence_exhausted", "Mandate retry sequence exhausted with no success")
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
        step = next_retry_step(row["previous_attempts"], is_mandate=False, failure_reason=row["failure_reason"])
        if step is None:
            return _exhausted_stop_or_escalate(d, row, "retry_sequence_exhausted", "Payment retry sequence exhausted with no success")
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

    # --- a new customer's low score doesn't mean "not worth trying" the
    # way a returning customer's does: the merchant already spent real
    # acquisition cost (ad spend, onboarding) getting this person to a
    # checkout at all, and that cost is sunk whether we try or not. A
    # cheap nudge (an SMS, not a human agent -- that's not economical for
    # a low-value transaction either way) has an asymmetric payoff here:
    # small downside if it fails, real upside (a recovered CAC-bearing
    # customer relationship) if it doesn't. A returning/VIP customer at
    # the same low score has no such recapture argument -- they're already
    # acquired, so a genuinely low-probability, low-value case for them
    # really is just not worth pursuing further.
    elif score < LOW_SCORE and row["customer_segment"] == "new":
        d.action = "SEND_MESSAGE"
        d.channel = _choose_channel(row, score)
        d.reasoning.append(
            f"Low model confidence ({score:.2f}), but this is a new customer — the acquisition cost already spent "
            f"getting them here is sunk either way, so a cheap nudge is worth it even at low odds, unlike a returning customer."
        )

    else:
        d.stopping_rule_triggered = "low_confidence_low_value"
        d.reasoning.append(f"Low recoverability score ({score:.2f}) and low value — not worth pursuing further.")
        return d

    # --- quiet-hours compliance note (applies to any customer contact) ------
    if d.action in ("SEND_MESSAGE",) and row["customer_local_hour"] in QUIET_HOURS:
        d.scheduled_hour = 9
        d.reasoning.append(f"Customer local hour is {row['customer_local_hour']}:00 (quiet hours) — deferring send to 09:00.")

    return d
