"""Security tests for the FastAPI service: rate limiting, API-key auth, and
input validation. Uses FastAPI's TestClient (in-process, no real network,
no server process to manage) so these run in CI."""
import pytest
from fastapi.testclient import TestClient

import api
from agent.rate_limiter import RateLimiter

VALID_TXN = {
    "transaction_id": "txn_test", "amount": 2000, "risk_type": "payment_failure",
    "failure_reason": "bank_timeout", "payment_method": "netbanking", "customer_segment": "returning",
}


@pytest.fixture(autouse=True)
def fresh_rate_limiter():
    """Each test gets an unpolluted rate limiter so tests can't bleed into
    each other via the module-level singleton."""
    api._limiter = RateLimiter(max_requests=api.RATE_LIMIT_MAX_REQUESTS, window_seconds=api.RATE_LIMIT_WINDOW_SECONDS)
    yield


@pytest.fixture
def client():
    return TestClient(api.app)


# --- input validation -------------------------------------------------------

def test_valid_decide_returns_200(client):
    resp = client.post("/decide", json=VALID_TXN)
    assert resp.status_code == 200
    assert resp.json()["action"] in ("RETRY_PAYMENT", "SEND_MESSAGE", "ESCALATE_HUMAN", "ESCALATE_OPS", "STOP")


def test_negative_amount_rejected(client):
    resp = client.post("/decide", json={**VALID_TXN, "amount": -50})
    assert resp.status_code == 422


def test_amount_over_cap_rejected(client):
    resp = client.post("/decide", json={**VALID_TXN, "amount": 50_000_000})
    assert resp.status_code == 422


def test_unknown_risk_type_rejected(client):
    resp = client.post("/decide", json={**VALID_TXN, "risk_type": "not_a_real_risk_type"})
    assert resp.status_code == 422


def test_failure_reason_must_match_risk_type(client):
    resp = client.post("/decide", json={**VALID_TXN, "failure_reason": "invoice_overdue_15d"})
    assert resp.status_code == 422


def test_out_of_range_hour_rejected(client):
    resp = client.post("/decide", json={**VALID_TXN, "customer_local_hour": 25})
    assert resp.status_code == 422


def test_sql_injection_flavored_transaction_id_is_handled_safely(client):
    """/decide never touches the state DB, so this should just be treated
    as an ordinary (if odd) string -- proves it doesn't crash the service."""
    resp = client.post("/decide", json={**VALID_TXN, "transaction_id": "x'; DROP TABLE transaction_state; --"})
    assert resp.status_code == 200


def test_oversized_batch_rejected(client):
    resp = client.post("/batch/demo", params={"n": api.MAX_BATCH_SIZE + 1})
    assert resp.status_code == 422


def test_zero_batch_rejected(client):
    resp = client.post("/batch/demo", params={"n": 0})
    assert resp.status_code == 422


def test_valid_batch_demo_returns_200(client):
    resp = client.post("/batch/demo", params={"n": 20, "seed": 1})
    assert resp.status_code == 200
    assert "summary" in resp.json()


# --- rate limiting -----------------------------------------------------------

def test_rate_limiter_blocks_after_threshold(client):
    api._limiter = RateLimiter(max_requests=3, window_seconds=60.0)
    codes = [client.get("/health").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3:] == [429, 429]


def test_rate_limited_response_has_retry_after(client):
    api._limiter = RateLimiter(max_requests=1, window_seconds=60.0)
    client.get("/health")
    resp = client.get("/health")
    assert resp.status_code == 429
    assert "retry-after" in resp.headers


# --- API-key auth --------------------------------------------------------

def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret123")
    assert client.post("/decide", json=VALID_TXN).status_code == 401
    assert client.post("/decide", json=VALID_TXN, headers={"X-API-Key": "nope"}).status_code == 401
    assert client.post("/decide", json=VALID_TXN, headers={"X-API-Key": "secret123"}).status_code == 200


def test_no_api_key_required_when_unset(client, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    assert client.post("/decide", json=VALID_TXN).status_code == 200


def test_health_never_requires_api_key(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret123")
    assert client.get("/health").status_code == 200
