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


def test_create_payment_link_passes_notes_through(monkeypatch):
    """notes is what lets api.py tag a recovery link with the original
    transaction it's recovering -- Razorpay copies it onto whatever
    Payment eventually gets made against the link, the same way it already
    does for an Order's notes (customer_segment)."""
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")

    captured = {}

    class FakePaymentLinkResource:
        def create(self, data):
            captured.update(data)
            return {"id": "plink_FAKE123", "short_url": "https://rzp.io/i/fake123"}

    class FakeClient:
        payment_link = FakePaymentLinkResource()

    monkeypatch.setattr(razorpay_live, "_get_client", lambda: FakeClient())
    razorpay_live.create_payment_link(
        amount_rupees=500, description="test", notes={"original_transaction_id": "pay_ROOT123"},
    )
    assert captured["notes"] == {"original_transaction_id": "pay_ROOT123"}


def test_create_payment_link_defaults_notes_to_empty_dict(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")

    captured = {}

    class FakePaymentLinkResource:
        def create(self, data):
            captured.update(data)
            return {"id": "plink_FAKE123", "short_url": "https://rzp.io/i/fake123"}

    class FakeClient:
        payment_link = FakePaymentLinkResource()

    monkeypatch.setattr(razorpay_live, "_get_client", lambda: FakeClient())
    razorpay_live.create_payment_link(amount_rupees=500, description="test")
    assert captured["notes"] == {}


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
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    result = email_sender.send_email("someone@example.com", "subject", "body")
    assert result.ok is False
    assert "not configured" in result.error.lower()


def test_email_no_recipient(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_fake_key")
    result = email_sender.send_email("", "subject", "body")
    assert result.ok is False
    assert "recipient" in result.error.lower()


def test_email_success(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_fake_key")

    sent = {}

    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        sent["url"] = req.full_url
        sent["headers"] = dict(req.header_items())
        sent["body"] = json.loads(req.data.decode())
        return FakeResponse()

    monkeypatch.setattr(email_sender.urllib.request, "urlopen", fake_urlopen)
    result = email_sender.send_email("customer@example.com", "Subject", "Body text")
    assert result.ok is True
    assert sent["url"] == email_sender.RESEND_API_URL
    assert sent["headers"]["Authorization"] == "Bearer re_fake_key"
    assert sent["body"]["to"] == ["customer@example.com"]
    assert sent["body"]["subject"] == "Subject"


def test_email_http_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_fake_key")

    def fake_urlopen(req, timeout=None):
        raise ConnectionRefusedError("network down")

    monkeypatch.setattr(email_sender.urllib.request, "urlopen", fake_urlopen)
    result = email_sender.send_email("customer@example.com", "Subject", "Body")
    assert result.ok is False
    assert "network down" in result.error


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


@pytest.fixture(autouse=True)
def isolated_customer_history(tmp_path):
    # Without this, the real SQLite file would persist across test runs --
    # previous_attempts would silently keep climbing every time the suite
    # runs, eventually crossing MAX_ATTEMPTS and changing which action a
    # test's fixed inputs produce. Each test gets a fresh, empty db.
    api.LIVE_CUSTOMER_HISTORY_DB_PATH = str(tmp_path / "live_customer_history.db")
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


def test_email_recipient_override_redirects_delivery(client, monkeypatch):
    """EMAIL_RECIPIENT_OVERRIDE exists for a real, narrow reason: Resend's
    free sandbox sender can only deliver to the account owner's own
    address, so testing against a real account needs every send routed
    there regardless of what email the (test) customer entered. Verifies
    both that send_email is actually called with the override address, and
    that the audit-log/response's displayed "sent_to" reflects where the
    email genuinely went -- not the original, misleading address."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("EMAIL_RECIPIENT_OVERRIDE", "verified@example.com")
    calls = []
    monkeypatch.setattr(
        api.email_sender, "send_email",
        lambda to_address, subject, body: (calls.append(to_address), email_sender.EmailResult(ok=True))[1],
    )
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_OVERRIDE001", "amount": 500000, "currency": "INR", "method": "card",
            "email": "someone.else@example.com", "error_reason": "payment_failed",
        }}},
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    result = resp.json()
    if result["action"] == "SEND_MESSAGE":
        assert calls == ["verified@example.com"]
        assert result["execution_detail"]["sent_to"] == "verified@example.com"


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


def test_webhook_tags_a_first_attempts_recovery_link_with_its_own_id(client, monkeypatch):
    """A first-attempt failure has nothing to be "a retry of" yet -- any
    recovery link it creates should be tagged with its own transaction ID
    as the root, and the response itself should report no retry_of_transaction_id."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    calls = []
    monkeypatch.setattr(
        api.razorpay_live, "create_payment_link",
        lambda **kwargs: (calls.append(kwargs), razorpay_live.PaymentLinkResult(ok=True, link_id="plink_x", short_url="https://rzp.io/i/x"))[1],
    )
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_ROOT_FIRST", "amount": 500000, "currency": "INR", "method": "netbanking",
            "email": "customer@example.com", "error_reason": "gateway_timeout",
        }}},
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    result = resp.json()
    assert result["retry_of_transaction_id"] is None
    if calls:  # a recovery link was actually created (RETRY_PAYMENT or SEND_MESSAGE)
        assert calls[0]["notes"]["original_transaction_id"] == "pay_ROOT_FIRST"


def test_webhook_propagates_root_transaction_id_through_a_retry_chain(client, monkeypatch):
    """If the customer's own retry (via a recovery link we created earlier)
    fails again, the *new* payment carries the original link's notes --
    including the root transaction. Any further recovery link this second
    failure creates must stay tagged with that same root, not restart the
    chain at this payment's own ID, or a purchase attempted 3+ times would
    fragment into multiple "purchases" again."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    calls = []
    monkeypatch.setattr(
        api.razorpay_live, "create_payment_link",
        lambda **kwargs: (calls.append(kwargs), razorpay_live.PaymentLinkResult(ok=True, link_id="plink_y", short_url="https://rzp.io/i/y"))[1],
    )
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_SECOND_ATTEMPT", "amount": 500000, "currency": "INR", "method": "netbanking",
            "email": "customer@example.com", "error_reason": "gateway_timeout",
            "notes": {"original_transaction_id": "pay_ROOT999", "customer_segment": "returning"},
        }}},
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    result = resp.json()
    assert result["retry_of_transaction_id"] == "pay_ROOT999"
    if calls:
        assert calls[0]["notes"]["original_transaction_id"] == "pay_ROOT999"

    logged = api._live_audit.for_transaction("pay_SECOND_ATTEMPT")
    assert logged.iloc[0]["retry_of_transaction_id"] == "pay_ROOT999"


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


# --- customer_local_hour derived from the real payment timestamp -----------

QUIET_HOUR_CREATED_AT = 1788557400   # 2026-09-05 03:00 IST
NORMAL_HOUR_CREATED_AT = 1788597000  # 2026-09-05 14:00 IST


def test_local_hour_from_created_at_quiet():
    assert razorpay_live._local_hour_from_created_at(QUIET_HOUR_CREATED_AT) == 3


def test_local_hour_from_created_at_normal():
    assert razorpay_live._local_hour_from_created_at(NORMAL_HOUR_CREATED_AT) == 14


def test_local_hour_from_created_at_missing_defaults_to_noon():
    assert razorpay_live._local_hour_from_created_at(None) == 12
    assert razorpay_live._local_hour_from_created_at(0) == 12  # falsy, treated as missing


def test_local_hour_from_created_at_malformed_defaults_to_noon():
    assert razorpay_live._local_hour_from_created_at("not-a-timestamp") == 12


def test_map_webhook_payment_to_row_uses_real_created_at():
    row = razorpay_live.map_webhook_payment_to_row({
        "id": "pay_x", "amount": 1000, "created_at": QUIET_HOUR_CREATED_AT,
    })
    assert row["customer_local_hour"] == 3


# --- quiet-hours deferral in the real webhook path --------------------------

def test_webhook_defers_email_during_quiet_hours_but_still_creates_link(client, monkeypatch):
    """A payment failing at 3am IST should not get an unprompted email --
    but the payment link (for the checkout page's own instant 'pay now'
    action, not proactive outreach) must still be created."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    email_calls = []
    monkeypatch.setattr(
        api.email_sender, "send_email",
        lambda **kw: (email_calls.append(kw), email_sender.EmailResult(ok=True))[1],
    )
    link_calls = []
    monkeypatch.setattr(
        api.razorpay_live, "create_payment_link",
        lambda **kw: (link_calls.append(kw), razorpay_live.PaymentLinkResult(ok=True, link_id="plink_q", short_url="https://rzp.io/i/q"))[1],
    )
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_QUIET001", "amount": 500000, "currency": "INR", "method": "netbanking",
            "email": "customer@example.com", "error_reason": "gateway_timeout",
            "created_at": QUIET_HOUR_CREATED_AT,
        }}},
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    assert resp.status_code == 200
    result = resp.json()

    # The link must always be created regardless of action, so "pay now" works.
    assert len(link_calls) == 1
    assert result["execution_detail"]["short_url"] == "https://rzp.io/i/q"
    assert result["execution_detail"]["deferred_quiet_hours"] is True
    assert result["execution_detail"]["emailed"] is False
    # The proactive email must NOT have been sent.
    assert len(email_calls) == 0


def test_webhook_sends_email_immediately_outside_quiet_hours(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    email_calls = []
    monkeypatch.setattr(
        api.email_sender, "send_email",
        lambda **kw: (email_calls.append(kw), email_sender.EmailResult(ok=True))[1],
    )
    monkeypatch.setattr(
        api.razorpay_live, "create_payment_link",
        lambda **kw: razorpay_live.PaymentLinkResult(ok=True, link_id="plink_n", short_url="https://rzp.io/i/n"),
    )
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_NORMAL001", "amount": 500000, "currency": "INR", "method": "netbanking",
            "email": "customer@example.com", "error_reason": "gateway_timeout",
            "created_at": NORMAL_HOUR_CREATED_AT,
        }}},
    }
    body = json.dumps(payload).encode()
    sig = _sign("whsec_test", body.decode())
    resp = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    result = resp.json()
    assert result["execution_detail"].get("deferred_quiet_hours") is not True
    assert len(email_calls) == 1
