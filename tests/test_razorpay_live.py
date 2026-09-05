"""Tests for agent/razorpay_live.py -- the real Razorpay SDK wrapper.

No live Razorpay account or network access is used or required. What *is*
tested for real: the cryptographic signature verification, since that's
pure HMAC-SHA256 math identical to what Razorpay's SDK does internally --
we can construct valid and tampered signatures ourselves with a fake secret
and prove our wrapper accepts/rejects them correctly. That's the
security-critical part of this integration (it's what stops a forged
"payment successful" callback), and it's fully verifiable offline.

order.create() itself (an actual HTTP call to Razorpay) is only exercised
via the "not configured" path here -- there's no way to test a real network
call without real credentials, and that's the one piece that genuinely
needs a live account (see pitch/razorpay_live_setup.md).
"""
import hashlib
import hmac

import pytest

from agent import razorpay_live


@pytest.fixture(autouse=True)
def clear_client_cache():
    """_get_client() memoizes on first call -- reset between tests so one
    test's monkeypatched env vars can't leak a stale client into another."""
    razorpay_live._client = None
    razorpay_live._client_checked = False
    yield
    razorpay_live._client = None
    razorpay_live._client_checked = False


# --- configuration state -----------------------------------------------------

def test_not_configured_by_default(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    assert razorpay_live.is_configured() is False
    assert razorpay_live.get_key_id() is None


def test_configured_when_both_env_vars_set(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
    assert razorpay_live.is_configured() is True
    assert razorpay_live.get_key_id() == "rzp_test_fake"


def test_not_configured_with_only_key_id(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    assert razorpay_live.is_configured() is False


def test_create_order_fails_clearly_when_not_configured(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    result = razorpay_live.create_order(amount_rupees=500)
    assert result.ok is False
    assert "not configured" in result.error.lower()


def test_verify_payment_signature_false_when_not_configured(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    assert razorpay_live.verify_payment_signature("order_x", "pay_x", "deadbeef") is False


# --- webhook signature verification (real HMAC math, no network) -----------

def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def test_webhook_signature_accepted_when_valid(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "my_webhook_secret")
    body = '{"event": "payment.failed", "payload": {}}'
    signature = _sign("my_webhook_secret", body)
    assert razorpay_live.verify_webhook_signature(body, signature) is True


def test_webhook_signature_rejected_when_tampered_body(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "my_webhook_secret")
    body = '{"event": "payment.failed", "payload": {}}'
    signature = _sign("my_webhook_secret", body)
    tampered_body = '{"event": "payment.captured", "payload": {}}'
    assert razorpay_live.verify_webhook_signature(tampered_body, signature) is False


def test_webhook_signature_rejected_when_wrong_secret(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "my_webhook_secret")
    body = '{"event": "payment.failed", "payload": {}}'
    signature = _sign("some_other_secret", body)
    assert razorpay_live.verify_webhook_signature(body, signature) is False


def test_webhook_signature_rejected_when_secret_not_set(monkeypatch):
    monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
    body = '{"event": "payment.failed"}'
    assert razorpay_live.verify_webhook_signature(body, "anything") is False


def test_webhook_signature_rejected_when_garbage_signature(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "my_webhook_secret")
    body = '{"event": "payment.failed"}'
    assert razorpay_live.verify_webhook_signature(body, "not-a-real-signature") is False


# --- webhook payload -> internal row mapping --------------------------------

def test_map_webhook_payment_to_row_known_reason():
    payment_entity = {
        "id": "pay_ABC123",
        "amount": 150000,  # paise -> 1500.00 rupees
        "currency": "INR",
        "method": "upi",
        "email": "jane.doe@example.com",
        "contact": "+919999999999",
        "error_reason": "insufficient_funds",
    }
    row = razorpay_live.map_webhook_payment_to_row(payment_entity)
    assert row["transaction_id"] == "pay_ABC123"
    assert row["amount"] == pytest.approx(1500.0)
    assert row["currency"] == "INR"
    assert row["payment_method"] == "upi"
    assert row["failure_reason"] == "insufficient_funds"
    assert row["risk_type"] == "payment_failure"
    assert row["customer_name"] == "Jane Doe"


def test_map_webhook_payment_to_row_unknown_reason_falls_back():
    payment_entity = {"id": "pay_XYZ", "amount": 1000, "error_reason": "some_brand_new_code_razorpay_added"}
    row = razorpay_live.map_webhook_payment_to_row(payment_entity)
    assert row["failure_reason"] == "issuer_declined"  # safe fallback, never raises


def test_map_webhook_payment_to_row_unknown_method_falls_back():
    payment_entity = {"id": "pay_XYZ", "amount": 1000, "method": "some_new_method"}
    row = razorpay_live.map_webhook_payment_to_row(payment_entity)
    assert row["payment_method"] == "card"


def test_map_webhook_payment_to_row_missing_fields_does_not_raise():
    row = razorpay_live.map_webhook_payment_to_row({})
    assert row["transaction_id"] == "unknown_payment"
    assert row["amount"] == 0.0
    assert row["failure_reason"] == "issuer_declined"


def test_map_webhook_payment_to_row_extracts_retry_of_transaction_id():
    """A payment made against a recovery link api.py created carries that
    link's notes -- including the original transaction it's recovering,
    which is what lets a retry chain collapse back to one purchase instead
    of reading as a second, independent one."""
    payment_entity = {
        "id": "pay_RETRY_ATTEMPT",
        "amount": 50000,
        "notes": {"original_transaction_id": "pay_ROOT123", "customer_segment": "returning"},
    }
    row = razorpay_live.map_webhook_payment_to_row(payment_entity)
    assert row["_retry_of_transaction_id"] == "pay_ROOT123"


def test_map_webhook_payment_to_row_no_retry_of_for_a_first_attempt():
    """A payment from the original checkout order (no recovery link
    involved yet) has no such note -- this is a first attempt, not a retry."""
    payment_entity = {"id": "pay_FIRST_ATTEMPT", "amount": 50000, "notes": {"customer_segment": "new"}}
    row = razorpay_live.map_webhook_payment_to_row(payment_entity)
    assert row["_retry_of_transaction_id"] is None


def test_parse_webhook_event_roundtrip():
    payload = razorpay_live.parse_webhook_event('{"event": "payment.failed", "x": 1}')
    assert payload["event"] == "payment.failed"
    assert payload["x"] == 1
