"""Tests for the messenger's offline-safe fallback path -- these must pass
with no ANTHROPIC_API_KEY and no audio backend (e.g. a bare CI runner)."""
import os

from agent.messenger import generate_message, synthesize_voice
from agent.policy import Decision
from helpers import make_row


def test_template_fallback_used_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    row = make_row(risk_type="payment_failure", failure_reason="bank_timeout", customer_name="Priya Shah")
    decision = Decision(transaction_id=row["transaction_id"], action="SEND_MESSAGE", channel="sms", recoverability_score=0.5)
    msg = generate_message(row, decision)
    assert isinstance(msg, str) and len(msg) > 0
    assert "Priya" in msg


def test_hinglish_template_for_voice_channel(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    row = make_row(risk_type="invoice_overdue", failure_reason="invoice_overdue_15d", customer_name="Rahul Verma")
    decision = Decision(transaction_id=row["transaction_id"], action="SEND_MESSAGE", channel="voice_hinglish", recoverability_score=0.5)
    msg = generate_message(row, decision)
    assert "Rahul" in msg


def test_synthesize_voice_never_raises(tmp_path):
    """On a CI runner with no audio backend this should return False, not raise."""
    out_path = str(tmp_path / "out.wav")
    result = synthesize_voice("Test message", out_path)
    assert isinstance(result, bool)


# --- tone escalates across repeat contact attempts --------------------------

def _decision(channel="sms"):
    return Decision(transaction_id="txn_tone", action="SEND_MESSAGE", channel=channel, recoverability_score=0.5)


def test_first_contact_message_differs_from_third(monkeypatch):
    """A customer contacted three times should be able to tell the messages
    apart -- not the exact same text every time."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    row0 = make_row(risk_type="payment_failure", failure_reason="bank_timeout", previous_attempts=0)
    row2 = make_row(risk_type="payment_failure", failure_reason="bank_timeout", previous_attempts=2)
    msg0 = generate_message(row0, _decision())
    msg2 = generate_message(row2, _decision())
    assert msg0 != msg2


def test_final_reminder_reads_more_urgent(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    row = make_row(risk_type="payment_failure", failure_reason="bank_timeout", previous_attempts=2)
    msg = generate_message(row, _decision())
    assert "final reminder" in msg.lower()


def test_tier_is_capped_at_two(monkeypatch):
    """previous_attempts beyond 2 (which the policy engine's max-attempts
    stopping rule would already have caught) must not index past the last
    tier -- capped, not an error."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    row_high = make_row(risk_type="payment_failure", failure_reason="bank_timeout", previous_attempts=10)
    row_capped = make_row(risk_type="payment_failure", failure_reason="bank_timeout", previous_attempts=2)
    assert generate_message(row_high, _decision()) == generate_message(row_capped, _decision())


def test_invoice_tone_also_escalates(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    row0 = make_row(risk_type="invoice_overdue", failure_reason="invoice_overdue_15d", previous_attempts=0)
    row2 = make_row(risk_type="invoice_overdue", failure_reason="invoice_overdue_15d", previous_attempts=2)
    assert generate_message(row0, _decision()) != generate_message(row2, _decision())
