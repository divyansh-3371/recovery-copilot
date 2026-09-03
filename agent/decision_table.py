"""
Failure-reason decision table -- the single source of truth for how the
policy engine treats each failure reason.

Before this module existed, the same knowledge was duplicated as separate
hardcoded sets in policy.py (CARD_UPDATE_REASONS, MANDATE_REASONS) and
simulator.py (its own RETRY_FRIENDLY_REASONS tuple) -- adding a new failure
reason meant hunting through multiple files and keeping them in sync by
hand, and it was easy for them to drift (which is exactly what happened:
see build_challenges.md #11). Now adding a reason means adding one row
here; policy.py, retry_sequencer.py, and simulator.py all read from it.
"""
from __future__ import annotations

from dataclasses import dataclass

# Categories:
#   customer_action_required -- blind retry can't fix it, the customer must act
#   transient_infra          -- likely to resolve itself fast, retry soon
#   balance_timing           -- needs time (salary/balance cycle), retry later
#   compliance_review        -- a risk/fraud signal -- NEVER auto-retry
#   engagement_nudge         -- checkout/OTP abandonment, needs a nudge not a retry
#   mandate_cycle            -- subscription/mandate-specific retry cadence
#   receivable_followup      -- B2B invoice, follow-up not retry


@dataclass(frozen=True)
class FailureReasonConfig:
    category: str
    blind_retry_effective: bool
    is_mandate: bool
    first_retry_delay_hours: float | None  # None if a blind retry never applies
    note: str


FAILURE_REASON_CONFIG: dict[str, FailureReasonConfig] = {
    # --- payment_failure ---
    "bank_timeout": FailureReasonConfig(
        "transient_infra", True, False, 0.5,
        "Bank/gateway timeout -- almost always transient, retry almost immediately."),
    "network_drop": FailureReasonConfig(
        "transient_infra", True, False, 0.5,
        "Connection dropped mid-payment -- transient, retry almost immediately."),
    "insufficient_funds": FailureReasonConfig(
        "balance_timing", True, False, 24.0,
        "Balance was short -- retrying immediately just fails again; wait for a salary/balance cycle."),
    "issuer_declined": FailureReasonConfig(
        "balance_timing", False, False, 12.0,
        "Generic issuer decline -- ambiguous cause, a single moderate-delay retry, no card-fault assumed."),
    "card_expired": FailureReasonConfig(
        "customer_action_required", False, False, None,
        "Card on file has expired -- a blind retry cannot succeed; the customer must update it."),
    "wrong_cvv": FailureReasonConfig(
        "customer_action_required", False, False, None,
        "CVV mismatch -- a blind retry cannot succeed; the customer must re-enter details."),
    "risk_block": FailureReasonConfig(
        "compliance_review", False, False, None,
        "Blocked by a risk/fraud engine -- auto-retrying past this is itself a compliance risk "
        "(can look like card-testing/fraud evasion). Routes to human review, never auto-retried."),

    # --- checkout_abandonment ---
    "cart_abandoned_otp": FailureReasonConfig(
        "engagement_nudge", False, False, None,
        "Dropped at the OTP step -- needs a nudge to finish, not a payment retry."),
    "cart_abandoned_payment_page": FailureReasonConfig(
        "engagement_nudge", False, False, None,
        "Dropped at the payment page -- needs a nudge to finish, not a payment retry."),
    "price_hesitation": FailureReasonConfig(
        "engagement_nudge", False, False, None,
        "Checkout not completed, likely price hesitation -- needs a nudge, not a retry."),

    # --- subscription_failure ---
    "mandate_expired": FailureReasonConfig(
        "mandate_cycle", False, True, 2.0,
        "Mandate has expired -- an automatic re-presentment can still briefly succeed; "
        "escalates to a manual re-authorization link if it doesn't."),
    "mandate_insufficient_funds": FailureReasonConfig(
        "mandate_cycle", True, True, 24.0,
        "Mandate hit insufficient balance -- wait for a salary/balance cycle before re-presenting."),
    "mandate_bank_error": FailureReasonConfig(
        "mandate_cycle", True, True, 2.0,
        "Bank-side mandate error -- likely transient, re-present soon."),

    # --- invoice_overdue ---
    "invoice_overdue_15d": FailureReasonConfig(
        "receivable_followup", False, False, None,
        "B2B invoice 15 days overdue -- a follow-up nudge, not a payment retry."),
    "invoice_overdue_30d": FailureReasonConfig(
        "receivable_followup", False, False, None,
        "B2B invoice 30 days overdue -- a firmer follow-up nudge."),
    "invoice_overdue_45plus": FailureReasonConfig(
        "receivable_followup", False, False, None,
        "B2B invoice significantly overdue -- follow-up, likely worth human/legal escalation at high value."),
}


def get_config(failure_reason: str) -> FailureReasonConfig:
    """Falls back to a conservative default for any failure reason not yet
    in the table -- an unrecognized reason should never silently get
    auto-retried; better to require a look before acting."""
    return FAILURE_REASON_CONFIG.get(
        failure_reason,
        FailureReasonConfig(
            "customer_action_required", False, False, None,
            f"Unrecognized failure reason '{failure_reason}' -- defaulting to no blind retry.",
        ),
    )


CUSTOMER_ACTION_REASONS = frozenset(k for k, v in FAILURE_REASON_CONFIG.items() if v.category == "customer_action_required")
COMPLIANCE_REVIEW_REASONS = frozenset(k for k, v in FAILURE_REASON_CONFIG.items() if v.category == "compliance_review")
RETRY_FRIENDLY_REASONS = frozenset(k for k, v in FAILURE_REASON_CONFIG.items() if v.blind_retry_effective)
MANDATE_REASONS = frozenset(k for k, v in FAILURE_REASON_CONFIG.items() if v.is_mandate)
