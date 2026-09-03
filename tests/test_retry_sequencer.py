"""Tests for the explicit mandate/payment retry sequencer."""
from agent.retry_sequencer import next_step


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
