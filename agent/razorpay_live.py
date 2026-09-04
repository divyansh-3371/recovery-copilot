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
import time
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


_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BACKOFF_SECONDS = 0.75


def _is_transient_network_error(exc: Exception) -> bool:
    """True for a dropped/aborted connection worth retrying (seen in
    practice: 'RemoteDisconnected' when a server closes the socket before
    responding) -- false for anything that's actually about the request
    itself (bad credentials, bad params), which retrying won't fix."""
    name = type(exc).__name__
    return name in ("ConnectionError", "ConnectionResetError", "RemoteDisconnected",
                     "ChunkedEncodingError", "ProtocolError", "ReadTimeout", "ConnectTimeout")


def create_order(amount_rupees: float, currency: str = "INR", receipt: str | None = None,
                  notes: dict | None = None) -> OrderResult:
    """Creates a real Razorpay order. amount_rupees is converted to paise
    (Razorpay's API works in the smallest currency unit) here, once, so
    every caller passes ordinary rupee amounts.

    Retries a few times on a transient dropped connection (this happens in
    practice -- a server closing a connection before responding -- and is
    not specific to bad credentials or a bad request, both of which come
    back as a clean HTTP error instead and are not retried)."""
    client = _get_client()
    if client is None:
        return OrderResult(ok=False, error="Razorpay is not configured on this server "
                                            "(RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set).")
    amount_paise = int(round(amount_rupees * 100))
    last_exc: Exception | None = None
    for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
        try:
            order = client.order.create(data={
                "amount": amount_paise,
                "currency": currency,
                "receipt": receipt or f"rc_{amount_paise}",
                "notes": notes or {},
            })
            return OrderResult(ok=True, order_id=order["id"], amount_paise=order["amount"],
                                currency=order["currency"])
        except Exception as exc:  # a real network/API failure -- surface it, don't crash the request
            last_exc = exc
            if _is_transient_network_error(exc) and attempt < _TRANSIENT_RETRY_ATTEMPTS - 1:
                time.sleep(_TRANSIENT_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            break
    return OrderResult(ok=False, error=str(last_exc))


@dataclass
class PaymentLinkResult:
    ok: bool
    link_id: str | None = None
    short_url: str | None = None
    error: str | None = None


def create_payment_link(amount_rupees: float, description: str, customer_name: str | None = None,
                         customer_email: str | None = None, customer_contact: str | None = None,
                         currency: str = "INR") -> PaymentLinkResult:
    """Creates a real, payable Razorpay Payment Link -- this is what makes
    a RETRY_PAYMENT decision an actual action rather than a label: the
    resulting short_url is a genuine URL a customer could open and pay
    through, not a description of what would happen. Retries transient
    connection failures the same way create_order() does."""
    client = _get_client()
    if client is None:
        return PaymentLinkResult(ok=False, error="Razorpay is not configured on this server "
                                                   "(RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set).")
    amount_paise = int(round(amount_rupees * 100))
    customer = {}
    if customer_name:
        customer["name"] = customer_name
    if customer_email:
        customer["email"] = customer_email
    if customer_contact:
        customer["contact"] = customer_contact

    last_exc: Exception | None = None
    for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
        try:
            link = client.payment_link.create(data={
                "amount": amount_paise,
                "currency": currency,
                "description": description,
                "customer": customer,
                "notify": {"sms": False, "email": False},  # we handle notification ourselves
                "reminder_enable": False,
            })
            return PaymentLinkResult(ok=True, link_id=link["id"], short_url=link["short_url"])
        except Exception as exc:
            last_exc = exc
            if _is_transient_network_error(exc) and attempt < _TRANSIENT_RETRY_ATTEMPTS - 1:
                time.sleep(_TRANSIENT_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            break
    return PaymentLinkResult(ok=False, error=str(last_exc))


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
#
# Verified against real Test Mode traffic (4 separate genuine webhook
# deliveries, triggered by 3 different documented "failure scenario" test
# cards -- insufficient_fund, payment_timed_out, authentication_failed):
# every one of them reports the *same* generic error_reason="payment_failed",
# error_code="BAD_REQUEST_ERROR" over the actual webhook payload. Razorpay's
# scenario names (in their test-card docs) are a label for which card
# triggers a failure in the UI, not a value that reaches this endpoint --
# so in Test Mode, everything correctly falls through to the "payment_failed"
# entry below regardless of which scenario card was used. The more specific
# entries (insufficient_fund, gateway_timeout, etc.) are what Razorpay's docs
# say a genuine Live Mode failure can report -- still unverified against real
# live traffic, kept here for when that's the mode in use. Unknown values
# fall back to a generic "issuer_declined" rather than raising, since a
# webhook receiver must never crash on an unexpected-but-real payload.
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

    # Razorpay has no native "customer segment" concept -- checkout.html
    # collects it and passes it through as an Order note, which Razorpay
    # copies onto the resulting Payment entity (verified live). Falls back
    # to "returning" for a payment that didn't originate from our own
    # checkout page (e.g. created directly via the Orders API elsewhere).
    notes = payment_entity.get("notes") or {}
    customer_segment = notes.get("customer_segment", "returning")
    if customer_segment not in ("new", "returning", "vip"):
        customer_segment = "returning"

    return {
        "transaction_id": payment_entity.get("id", "unknown_payment"),
        "customer_id": payment_entity.get("contact") or "unknown",
        "customer_name": email.split("@")[0].replace(".", " ").title(),
        "amount": float(amount_paise) / 100.0,
        "currency": payment_entity.get("currency", "INR"),
        "risk_type": "payment_failure",
        "failure_reason": failure_reason,
        "payment_method": payment_method,
        "customer_segment": customer_segment,
        "previous_attempts": 0,
        "do_not_contact": False,
        "customer_local_hour": 12,
        "days_since_event": 0,
        # raw values, kept only for observability (see RAZORPAY_ERROR_REASON_MAP's
        # note) -- not used by the classifier/policy, just logged so the map
        # above can be refined against what Razorpay actually sends
        "_raw_error_reason": payment_entity.get("error_reason"),
        "_raw_error_code": payment_entity.get("error_code"),
        "_raw_error_description": payment_entity.get("error_description"),
    }


def parse_webhook_event(raw_body: str) -> dict:
    return json.loads(raw_body)
