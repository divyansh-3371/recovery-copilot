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
