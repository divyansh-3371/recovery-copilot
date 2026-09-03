"""
Mandate / payment retry sequencer.

Rather than one blind retry, a failed payment or subscription mandate
follows an explicit multi-step sequence: what to try, after how long, and
with what fallback -- escalating in cost/intrusiveness only as earlier,
cheaper steps fail. This is the track's "mandate retry sequencer" direction
made an explicit, inspectable component rather than inline policy logic.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from agent.decision_table import get_config


@dataclass(frozen=True)
class RetryStep:
    step: int
    delay_hours: float
    method: str  # "same" | "fallback" | "manual_link"
    note: str


# indexed by previous_attempts (0 = the failure that just happened, no retry yet)
PAYMENT_RETRY_SEQUENCE: list[RetryStep] = [
    RetryStep(1, 0.5, "same", "Immediate retry on the same method — covers transient bank/network blips."),
    RetryStep(2, 6.0, "same", "Retry after 6h — covers a temporary insufficient-funds window."),
    RetryStep(3, 24.0, "fallback", "Same method has now failed twice — switch to a fallback payment method."),
]

MANDATE_RETRY_SEQUENCE: list[RetryStep] = [
    RetryStep(1, 2.0, "same", "Immediate mandate re-presentment."),
    RetryStep(2, 24.0, "same", "Re-present after 24h, aligned to typical salary-credit cycles."),
    RetryStep(3, 72.0, "manual_link", "Two silent re-presentments — send a manual re-authorization link instead."),
]


def next_step(previous_attempts: int, is_mandate: bool, failure_reason: str | None = None) -> RetryStep | None:
    """The next step in the sequence given how many attempts have already
    happened. Returns None once the sequence is exhausted (the policy's
    max-attempts stopping rule should already have caught this first).

    The *first* step's delay is tuned to the specific failure reason via
    the decision table when one is given -- a transient infra blip (bank
    timeout, network drop) should retry almost immediately, while an
    insufficient-funds failure retried in 30 minutes just fails again;
    it needs to wait for a balance/salary cycle. Later steps keep the base
    sequence's escalation (longer delay, then a method/channel change)
    regardless of the specific reason, since by that point the first,
    reason-tuned attempt has already failed."""
    sequence = MANDATE_RETRY_SEQUENCE if is_mandate else PAYMENT_RETRY_SEQUENCE
    if previous_attempts >= len(sequence):
        return None
    step = sequence[previous_attempts]

    if previous_attempts == 0 and failure_reason is not None:
        cfg = get_config(failure_reason)
        if cfg.first_retry_delay_hours is not None and cfg.first_retry_delay_hours != step.delay_hours:
            step = replace(
                step, delay_hours=cfg.first_retry_delay_hours,
                note=f"{step.note} Delay tuned to '{failure_reason}': {cfg.note}",
            )

    return step
