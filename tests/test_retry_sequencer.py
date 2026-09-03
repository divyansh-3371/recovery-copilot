"""Tests for the explicit mandate/payment retry sequencer."""
from agent.retry_sequencer import PAYMENT_RETRY_SEQUENCE, next_step


def test_payment_sequence_progresses_in_order():
    steps = [next_step(a, is_mandate=False) for a in range(3)]
    assert [s.step for s in steps] == [1, 2, 3]
    assert steps[-1].method == "fallback"  # last payment step switches method


def test_payment_sequence_exhausts():
    assert next_step(3, is_mandate=False) is None


def test_mandate_sequence_ends_in_manual_link():
    steps = [next_step(a, is_mandate=True) for a in range(3)]
    assert steps[-1].method == "manual_link"


def test_mandate_and_payment_sequences_differ():
    assert next_step(0, is_mandate=True) != next_step(0, is_mandate=False)


def test_first_step_delay_tuned_to_transient_infra_reason():
    """bank_timeout is transient -- retry almost immediately, per the
    decision table, not the base sequence's untuned default."""
    step = next_step(0, is_mandate=False, failure_reason="bank_timeout")
    assert step.delay_hours == 0.5


def test_first_step_delay_tuned_to_balance_timing_reason():
    """insufficient_funds needs to wait for a balance/salary cycle -- a
    30-minute retry would just fail again, so this must NOT be 0.5h even
    though it's the same sequence position as the transient-infra case."""
    step = next_step(0, is_mandate=False, failure_reason="insufficient_funds")
    assert step.delay_hours == 24.0


def test_later_steps_are_not_reason_tuned():
    """Only the first attempt is reason-tuned -- by step 2 the reason-tuned
    first attempt has already failed, so the base sequence's own escalation
    applies regardless of which specific reason started it."""
    tuned = next_step(1, is_mandate=False, failure_reason="bank_timeout")
    untuned = next_step(1, is_mandate=False, failure_reason=None)
    assert tuned.delay_hours == untuned.delay_hours


def test_no_failure_reason_uses_base_sequence_unchanged():
    step = next_step(0, is_mandate=False, failure_reason=None)
    assert step.delay_hours == PAYMENT_RETRY_SEQUENCE[0].delay_hours
