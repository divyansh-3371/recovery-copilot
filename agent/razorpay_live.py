"""
Real Razorpay integration -- order creation, payment-signature verification,
and webhook-signature verification, against actual Razorpay servers using
the official Python SDK.

This is deliberately a separate module from agent/razorpay_client.py:
razorpay_client.py maps an agent DECISION to the API call it would
illustratively trigger (a stub, used in the dashboard's "Technical
details" view -- no network call, no credentials needed). This module is
the real client -- it makes actual HTTP calls to Razorpay when configured.

Configuration is entirely via environment variables, never hardcoded or
logged:
    RAZORPAY_KEY_ID          -- public; safe to send to a browser/frontend
    RAZORPAY_KEY_SECRET      -- private; backend-only, never sent to a client
    RAZORPAY_WEBHOOK_SECRET  -- private; must match the secret configured
                                 for the webhook in the Razorpay dashboard

If the key ID/secret aren't set, every function here degrades to a clear
"not configured" result instead of raising -- so the rest of the app (and
its tests) work fine with no live credentials present. See
pitch/razorpay_live_setup.md for how to actually connect a real account.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import razorpay
from razorpay.errors import SignatureVerificationError

_client: razorpay.Client | None = None
_client_checked = False


def is_configured() -> bool:
    return bool(os.environ.get("RAZORPAY_KEY_ID")) and bool(os.environ.get("RAZORPAY_KEY_SECRET"))


def get_key_id() -> str | None:
    """The public Key ID -- this is the only credential a frontend ever sees."""
    return os.environ.get("RAZORPAY_KEY_ID")


def _get_client() -> razorpay.Client | None:
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if key_id and key_secret:
        _client = razorpay.Client(auth=(key_id, key_secret))
    return _client


@dataclass
class OrderResult:
    ok: bool
    order_id: str | None = None
    amount_paise: int | None = None
    currency: str | None = None
    error: str | None = None


def create_order(amount_rupees: float, currency: str = "INR", receipt: str | None = None,
                  notes: dict | None = None) -> OrderResult:
    """Creates a real Razorpay order. amount_rupees is converted to paise
    (Razorpay's API works in the smallest currency unit) here, once, so
    every caller passes ordinary rupee amounts."""
    client = _get_client()
    if client is None:
        return OrderResult(ok=False, error="Razorpay is not configured on this server "
                                            "(RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set).")
    amount_paise = int(round(amount_rupees * 100))
    try:
        order = client.order.create(data={
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt or f"rc_{amount_paise}",
            "notes": notes or {},
        })
        return OrderResult(ok=True, order_id=order["id"], amount_paise=order["amount"], currency=order["currency"])
    except Exception as exc:  # a real network/API failure -- surface it, don't crash the request
        return OrderResult(ok=False, error=str(exc))


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """True only if the signature genuinely matches order_id|payment_id
    signed with our Key Secret -- this is what stops someone from faking a
    'payment successful' callback from the browser alone."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
        return True
    except SignatureVerificationError:
        return False
    except Exception:
        return False


def verify_webhook_signature(raw_body: str, signature: str) -> bool:
    """True only if `signature` (the X-Razorpay-Signature header) matches
    an HMAC-SHA256 of the exact raw request body using the webhook secret.
    Must be checked against the raw bytes/string as received -- parsing to
    JSON and re-serializing before checking would break the signature."""
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        return False
    try:
        razorpay.Utility(None).verify_webhook_signature(raw_body, signature, secret)
        return True
    except SignatureVerificationError:
        return False
    except Exception:
        return False


# Best-effort mapping from Razorpay's documented payment error_reason/
# error_code values to this project's own failure-reason taxonomy.
# Informed by Razorpay's public API documentation, not verified against a
# large volume of live traffic -- refine this against real webhook payloads
# once connected to a live account. Unknown values fall back to a generic
# "issuer_declined" rather than raising, since a webhook receiver must never
# crash on an unexpected-but-real payload.
RAZORPAY_ERROR_REASON_MAP = {
    "payment_failed": "issuer_declined",
    "payment_declined": "issuer_declined",
    "insufficient_funds": "insufficient_funds",
    "card_declined": "issuer_declined",
    "expired_card": "card_expired",
    "invalid_cvv": "wrong_cvv",
    "incorrect_cvv": "wrong_cvv",
    "gateway_error": "bank_timeout",
    "gateway_timeout": "bank_timeout",
    "server_error": "bank_timeout",
    "network_error": "network_drop",
    "risk_check_failed": "risk_block",
    "fraud_suspected": "risk_block",
}
_KNOWN_METHODS = {"card", "upi", "netbanking", "wallet"}


def map_webhook_payment_to_row(payment_entity: dict) -> dict:
    """Maps a Razorpay `payment.entity` webhook payload (from a
    payment.failed event) into the row shape agent/classifier.py and
    agent/policy.py expect. Every field has a safe fallback -- a webhook
    receiver must degrade gracefully on a real but unexpected payload, not
    500 on a KeyError."""
    method = (payment_entity.get("method") or "card").lower()
    payment_method = method if method in _KNOWN_METHODS else "card"

    error_reason_raw = (payment_entity.get("error_reason") or payment_entity.get("error_code") or "").lower()
    failure_reason = RAZORPAY_ERROR_REASON_MAP.get(error_reason_raw, "issuer_declined")

    amount_paise = payment_entity.get("amount", 0) or 0
    email = payment_entity.get("email") or "customer@example.com"

    return {
        "transaction_id": payment_entity.get("id", "unknown_payment"),
        "customer_id": payment_entity.get("contact") or "unknown",
        "customer_name": email.split("@")[0].replace(".", " ").title(),
        "amount": float(amount_paise) / 100.0,
        "currency": payment_entity.get("currency", "INR"),
        "risk_type": "payment_failure",
        "failure_reason": failure_reason,
        "payment_method": payment_method,
        # not knowable from a webhook payload alone -- a real integration
        # would look this customer up in the merchant's own CRM/database
        "customer_segment": "returning",
        "previous_attempts": 0,
        "do_not_contact": False,
        "customer_local_hour": 12,
        "days_since_event": 0,
    }


def parse_webhook_event(raw_body: str) -> dict:
    return json.loads(raw_body)
