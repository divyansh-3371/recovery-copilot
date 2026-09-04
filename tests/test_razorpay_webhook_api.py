"""API-level tests for the real Razorpay integration surface in api.py:
/razorpay/status, /checkout, /checkout/create-order, /checkout/verify, and
the webhook receiver /webhooks/razorpay.

No live Razorpay account is used. Order creation itself (an outbound HTTP
call) is monkeypatched at the agent.razorpay_live boundary; everything
else -- webhook signature verification, payload mapping, and the actual
score/decide pipeline the webhook triggers -- runs for real, exactly as it
would against genuine Razorpay traffic.
"""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import api
from agent import razorpay_live
from agent.audit import AuditTrail
from agent.rate_limiter import RateLimiter


@pytest.fixture(autouse=True)
def fresh_rate_limiter():
    api._limiter = RateLimiter(max_requests=api.RATE_LIMIT_MAX_REQUESTS, window_seconds=api.RATE_LIMIT_WINDOW_SECONDS)
    yield


@pytest.fixture(autouse=True)
def isolated_live_audit(tmp_path):
    """Real webhook processing writes to the live audit trail -- point it at
    a throwaway file per test instead of the shared data/live_audit_log.jsonl."""
    api._live_audit = AuditTrail(path=str(tmp_path / "live_audit_log.jsonl"))
    yield


@pytest.fixture(autouse=True)
def clear_razorpay_client_cache():
    razorpay_live._client = None
    razorpay_live._client_checked = False
    yield
    razorpay_live._client = None
    razorpay_live._client_checked = False


@pytest.fixture
def client():
    return TestClient(api.app)


def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


# --- /razorpay/status --------------------------------------------------------

def test_status_false_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    resp = client.get("/razorpay/status")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False}


def test_status_true_when_configured(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
    resp = client.get("/razorpay/status")
    assert resp.json() == {"configured": True}


# --- /checkout (static page) -------------------------------------------------

def test_checkout_page_serves_html(client):
    resp = client.get("/checkout")
    assert resp.status_code == 200
    assert "checkout.razorpay.com" in resp.text


# --- /checkout/create-order ---------------------------------------------------

def test_create_order_503_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    resp = client.post("/checkout/create-order", json={"amount": 500})
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


def test_create_order_rejects_non_positive_amount(client):
    resp = client.post("/checkout/create-order", json={"amount": -5})
    assert resp.status_code == 422


def test_create_order_returns_order_when_configured(client, monkeypatch):
    monkeypatch.setattr(
        razorpay_live, "create_order",
        lambda amount_rupees, currency="INR", receipt=None, notes=None: razorpay_live.OrderResult(
            ok=True, order_id="order_FAKE123", amount_paise=int(amount_rupees * 100), currency="INR",
        ),
    )
    monkeypatch.setattr(razorpay_live, "get_key_id", lambda: "rzp_test_fake")
    resp = client.post("/checkout/create-order", json={"amount": 500})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["order_id"] == "order_FAKE123"
    assert body["amount"] == 50000
    assert body["key_id"] == "rzp_test_fake"
    # the Key Secret must never appear in a response to the browser
    assert "secret" not in json.dumps(body).lower()


# --- /checkout/verify ---------------------------------------------------------

def test_verify_returns_false_for_bad_signature(client, monkeypatch):
    monkeypatch.setattr(razorpay_live, "verify_payment_signature", lambda o, p, s: False)
    resp = client.post("/checkout/verify", json={
        "razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x", "razorpay_signature": "bad",
    })
    assert resp.status_code == 200
    assert resp.json() == {"ok": False}


def test_verify_returns_true_for_good_signature(client, monkeypatch):
    monkeypatch.setattr(razorpay_live, "verify_payment_signature", lambda o, p, s: True)
    resp = client.post("/checkout/verify", json={
        "razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x", "razorpay_signature": "good",
    })
    assert resp.json() == {"ok": True}


def test_verify_rejects_missing_fields(client):
    resp = client.post("/checkout/verify", json={"razorpay_order_id": "order_x"})
    assert resp.status_code == 422


# --- /webhooks/razorpay -------------------------------------------------------

def test_webhook_rejects_missing_signature(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    resp = client.post("/webhooks/razorpay", content=b'{"event": "payment.failed"}')
    assert resp.status_code == 400


def test_webhook_rejects_wrong_signature(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    body = b'{"event": "payment.failed"}'
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": "wrong"})
    assert resp.status_code == 400


def test_webhook_rejects_when_secret_not_configured(client, monkeypatch):
    monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
    body = b'{"event": "payment.failed"}'
    sig = _sign("whatever", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    assert resp.status_code == 400


def test_webhook_ignores_non_failure_events(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    body = json.dumps({"event": "payment.captured", "payload": {}}).encode()
    sig = _sign("whsec_test", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored", "event": "payment.captured"}


def test_webhook_rejects_malformed_payment_failed_payload(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    body = json.dumps({"event": "payment.failed", "payload": {}}).encode()
    sig = _sign("whsec_test", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    assert resp.status_code == 400


def test_webhook_processes_real_payment_failed_event_end_to_end(client, monkeypatch, tmp_path):
    """The core promise of this integration: a genuinely-signed
    payment.failed webhook flows all the way through score -> decide ->
    audit log, with no human/dashboard action in between."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_LIVE001",
                    "amount": 250000,  # paise -> 2500 rupees
                    "currency": "INR",
                    "method": "card",
                    "email": "test.customer@example.com",
                    "contact": "+919876543210",
                    "error_reason": "insufficient_funds",
                }
            }
        },
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())

    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "processed"
    assert result["action"] in ("RETRY_PAYMENT", "SEND_MESSAGE", "ESCALATE_HUMAN", "ESCALATE_COLLECTIONS",
                                 "ESCALATE_OPS", "STOP")
    assert 0.0 <= result["recoverability_score"] <= 1.0

    logged = api._live_audit.for_transaction("pay_LIVE001")
    assert len(logged) == 1
    assert logged.iloc[0]["action"] == result["action"]
    assert logged.iloc[0]["failure_reason"] == "insufficient_funds"
    assert logged.iloc[0]["source"] == "razorpay_webhook"


def test_webhook_replayed_tampered_body_is_rejected(client, monkeypatch):
    """A signature computed over the original body must not validate a
    body that's since been modified -- proves this isn't just checking
    'is there a signature header' but the actual content."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    original_body = json.dumps({"event": "payment.failed", "payload": {}}).encode()
    sig = _sign("whsec_test", original_body.decode())
    tampered_body = json.dumps({"event": "payment.captured", "payload": {}}).encode()
    resp = client.post("/webhooks/razorpay", content=tampered_body, headers={"X-Razorpay-Signature": sig})
    assert resp.status_code == 400


# --- /checkout/decision/{payment_id} -----------------------------------------

def test_decision_not_found_for_unknown_payment_id(client):
    resp = client.get("/checkout/decision/pay_never_happened")
    assert resp.status_code == 200
    assert resp.json() == {"found": False}


def test_decision_found_after_a_real_webhook(client, monkeypatch):
    """The polling endpoint checkout.html relies on -- after a genuine
    webhook has been processed, its decision must be look-up-able by
    payment_id, with plain JSON-serializable types (this is what would
    break on a raw numpy/pandas scalar leaking through)."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_POLLME001", "amount": 100000, "currency": "INR",
            "method": "card", "email": "poll@example.com", "error_reason": "payment_failed",
        }}},
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())
    webhook_resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    assert webhook_resp.status_code == 200

    resp = client.get("/checkout/decision/pay_POLLME001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert isinstance(data["action"], str)
    assert isinstance(data["reasoning"], list)
    assert isinstance(data["recoverability_score"], float)
    assert data["action"] == webhook_resp.json()["action"]
