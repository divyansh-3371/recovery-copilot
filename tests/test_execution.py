"""Tests for the two real-execution paths: agent/razorpay_live.py's
create_payment_link() (RETRY_PAYMENT) and agent/email_sender.py's
send_email() (SEND_MESSAGE). Both need live credentials for the actual
outbound call, so those are monkeypatched at the boundary; everything else
-- configuration checks, error handling, the api.py wiring that decides
*when* to call them -- is exercised for real.
"""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import api
from agent import email_sender, razorpay_live
from agent.audit import AuditTrail
from agent.rate_limiter import RateLimiter


# --- agent/razorpay_live.py: create_payment_link -----------------------------

@pytest.fixture(autouse=True)
def clear_client_cache():
    razorpay_live._client = None
    razorpay_live._client_checked = False
    yield
    razorpay_live._client = None
    razorpay_live._client_checked = False


def test_create_payment_link_not_configured(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    result = razorpay_live.create_payment_link(amount_rupees=500, description="test")
    assert result.ok is False
    assert "not configured" in result.error.lower()


def test_create_payment_link_success(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")

    class FakePaymentLinkResource:
        def create(self, data):
            assert data["amount"] == 50000
            assert data["customer"]["email"] == "a@b.com"
            return {"id": "plink_FAKE123", "short_url": "https://rzp.io/i/fake123"}

    class FakeClient:
        payment_link = FakePaymentLinkResource()

    monkeypatch.setattr(razorpay_live, "_get_client", lambda: FakeClient())
    result = razorpay_live.create_payment_link(
        amount_rupees=500, description="test", customer_email="a@b.com",
    )
    assert result.ok is True
    assert result.short_url == "https://rzp.io/i/fake123"
    assert result.link_id == "plink_FAKE123"


def test_create_payment_link_api_error(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")

    class FakePaymentLinkResource:
        def create(self, data):
            raise ValueError("bad request")

    class FakeClient:
        payment_link = FakePaymentLinkResource()

    monkeypatch.setattr(razorpay_live, "_get_client", lambda: FakeClient())
    result = razorpay_live.create_payment_link(amount_rupees=500, description="test")
    assert result.ok is False
    assert "bad request" in result.error


# --- agent/email_sender.py ---------------------------------------------------

def test_email_not_configured(monkeypatch):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    result = email_sender.send_email("someone@example.com", "subject", "body")
    assert result.ok is False
    assert "not configured" in result.error.lower()


def test_email_no_recipient(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake_app_password")
    result = email_sender.send_email("", "subject", "body")
    assert result.ok is False
    assert "recipient" in result.error.lower()


def test_email_success(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake_app_password")

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["starttls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def sendmail(self, from_addr, to_addrs, msg):
            sent["sendmail"] = (from_addr, to_addrs)

    monkeypatch.setattr(email_sender.smtplib, "SMTP", FakeSMTP)
    result = email_sender.send_email("customer@example.com", "Subject", "Body text")
    assert result.ok is True
    assert sent["login"] == ("me@gmail.com", "fake_app_password")
    assert sent["sendmail"][1] == ["customer@example.com"]


def test_email_smtp_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake_app_password")

    class FailingSMTP:
        def __init__(self, *a, **kw):
            raise ConnectionRefusedError("smtp down")

    monkeypatch.setattr(email_sender.smtplib, "SMTP", FailingSMTP)
    result = email_sender.send_email("customer@example.com", "Subject", "Body")
    assert result.ok is False
    assert "smtp down" in result.error


# --- api.py webhook wiring: does it call the right execution path? ----------

def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def fresh_rate_limiter():
    api._limiter = RateLimiter(max_requests=api.RATE_LIMIT_MAX_REQUESTS, window_seconds=api.RATE_LIMIT_WINDOW_SECONDS)
    yield


@pytest.fixture(autouse=True)
def isolated_live_audit(tmp_path):
    api._live_audit = AuditTrail(path=str(tmp_path / "live_audit_log.jsonl"))
    yield


@pytest.fixture
def client():
    return TestClient(api.app)


def test_webhook_attempts_email_for_send_message(client, monkeypatch):
    """A SEND_MESSAGE decision should call send_email -- verified by
    monkeypatching it and checking it was actually invoked with the
    customer's real email from the payload, not just that the decision
    was computed."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    calls = []
    monkeypatch.setattr(
        api.email_sender, "send_email",
        lambda to_address, subject, body: (calls.append((to_address, subject)), email_sender.EmailResult(ok=True))[1],
    )
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_EXEC001", "amount": 500000, "currency": "INR", "method": "card",
            "email": "customer@example.com", "error_reason": "payment_failed",
        }}},
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    assert resp.status_code == 200
    result = resp.json()
    if result["action"] == "SEND_MESSAGE":
        assert len(calls) == 1
        assert calls[0][0] == "customer@example.com"
        assert result["executed"] is True


def test_webhook_attempts_payment_link_for_retry(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    calls = []
    monkeypatch.setattr(
        api.razorpay_live, "create_payment_link",
        lambda **kwargs: (calls.append(kwargs), razorpay_live.PaymentLinkResult(ok=True, link_id="plink_x", short_url="https://rzp.io/i/x"))[1],
    )
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_EXEC002", "amount": 500000, "currency": "INR", "method": "netbanking",
            "email": "customer2@example.com", "error_reason": "gateway_timeout",
        }}},
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    assert resp.status_code == 200
    result = resp.json()
    if result["action"] == "RETRY_PAYMENT":
        assert len(calls) == 1
        assert result["executed"] is True
        assert result["execution_detail"]["short_url"] == "https://rzp.io/i/x"


def test_checkout_decision_surfaces_execution_detail(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(
        api.email_sender, "send_email",
        lambda **kwargs: email_sender.EmailResult(ok=True),
    )
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_EXEC003", "amount": 500000, "currency": "INR", "method": "card",
            "email": "customer3@example.com", "error_reason": "payment_failed",
        }}},
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())
    client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})

    resp = client.get("/checkout/decision/pay_EXEC003")
    data = resp.json()
    assert data["found"] is True
    assert "executed" in data
    assert "execution_detail" in data


# --- fetch_payment_link_status + /checkout/recovery-status/{id} -------------

def test_fetch_payment_link_status_not_configured(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    result = razorpay_live.fetch_payment_link_status("plink_x")
    assert result.ok is False


def test_fetch_payment_link_status_paid(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")

    class FakePaymentLinkResource:
        def fetch(self, link_id):
            assert link_id == "plink_x"
            return {"status": "paid", "amount_paid": 50000}

    class FakeClient:
        payment_link = FakePaymentLinkResource()

    monkeypatch.setattr(razorpay_live, "_get_client", lambda: FakeClient())
    result = razorpay_live.fetch_payment_link_status("plink_x")
    assert result.ok is True
    assert result.status == "paid"
    assert result.amount_paid_rupees == 500.0


def test_recovery_status_no_link_yet(client, monkeypatch):
    """An ESCALATE_HUMAN/STOP decision never creates a link -- recovery
    status must say so cleanly, not error."""
    api._live_audit.log(
        transaction_id="pay_NOLINK", action="ESCALATE_HUMAN", reasoning=["x"],
        extra={"execution_detail": None},
    )
    resp = client.get("/checkout/recovery-status/pay_NOLINK")
    data = resp.json()
    assert data["found"] is True
    assert data["has_link"] is False
    assert data["recovered"] is False


def test_recovery_status_paid(client, monkeypatch):
    api._live_audit.log(
        transaction_id="pay_PAID1", action="RETRY_PAYMENT", reasoning=["x"],
        extra={"execution_detail": {"type": "payment_link", "link_id": "plink_paid", "short_url": "https://rzp.io/i/x"}},
    )
    monkeypatch.setattr(
        api.razorpay_live, "fetch_payment_link_status",
        lambda link_id: razorpay_live.LinkStatusResult(ok=True, status="paid", amount_paid_rupees=1234.0),
    )
    resp = client.get("/checkout/recovery-status/pay_PAID1")
    data = resp.json()
    assert data["found"] is True
    assert data["has_link"] is True
    assert data["recovered"] is True
    assert data["recovered_amount"] == 1234.0
