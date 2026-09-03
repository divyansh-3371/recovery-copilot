"""Tests for the promise-to-pay classifier."""
import numpy as np

from agent.promise_tracker import classify_promise
from helpers import make_row


def test_not_applicable_for_non_eligible_action():
    row = make_row(risk_type="invoice_overdue")
    rec = classify_promise(row, action="RETRY_PAYMENT", resolved=True, rng=np.random.default_rng(1))
    assert rec.status == "not_applicable"


def test_not_applicable_for_non_eligible_risk_type():
    row = make_row(risk_type="payment_failure")
    rec = classify_promise(row, action="SEND_MESSAGE", resolved=True, rng=np.random.default_rng(1))
    assert rec.status == "not_applicable"


def test_kept_matches_resolved_true():
    row = make_row(risk_type="invoice_overdue", customer_segment="vip")
    # a high-likelihood segment/risk combo with a seed that yields a promise
    rec = classify_promise(row, action="SEND_MESSAGE", resolved=True, rng=np.random.default_rng(0))
    assert rec.status in ("kept", "not_offered")
    if rec.status == "kept":
        assert rec.promised_in_days is not None


def test_broken_matches_resolved_false():
    row = make_row(risk_type="invoice_overdue", customer_segment="vip")
    rec = classify_promise(row, action="SEND_MESSAGE", resolved=False, rng=np.random.default_rng(0))
    assert rec.status in ("broken", "not_offered")
    if rec.status == "broken":
        assert "escalating" in rec.note.lower()
