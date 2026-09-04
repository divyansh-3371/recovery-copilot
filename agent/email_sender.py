"""
Real email delivery for the SEND_MESSAGE / RETRY_PAYMENT actions, via
Resend's HTTP API (https://api.resend.com) -- this is what turns a
generated message from text into an actual delivered nudge for a real
(live-webhook-driven) transaction.

Deliberately NOT wired into the synthetic pipeline (data/generate_data.py
never generates an email address at all -- see its customer_name-only
Faker call) -- this module is only ever called from api.py's real webhook
handler, never from /dashboard/try or /decide, so a demo run of the
synthetic batch can never accidentally email a real person.

Why an HTTP API instead of SMTP: this project's dev network blocks all
outbound SMTP ports (25, 465, 587) -- confirmed with raw TCP connection
tests, not just an app-level timeout -- which is a common restriction on
residential ISPs to prevent spam-relay abuse. An HTTPS API call on port
443 (identical in shape to every other outbound call this project already
makes -- Razorpay, GitHub) isn't affected by that block.

Configuration, via environment variables, never hardcoded or logged:
    RESEND_API_KEY  -- from https://resend.com/api-keys (needs a free account)
    RESEND_FROM     -- optional; defaults to Resend's own sandbox sender
                       (onboarding@resend.dev), which works with no domain
                       verification but can only deliver to the address
                       that owns the Resend account in that unverified state

If unset, send_email() returns a clear "not configured" result instead of
raising -- same degrade-gracefully pattern as agent/razorpay_live.py.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "Recovery Copilot <onboarding@resend.dev>"


@dataclass
class EmailResult:
    ok: bool
    error: str | None = None


def is_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def send_email(to_address: str, subject: str, body: str) -> EmailResult:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return EmailResult(ok=False, error="Email is not configured on this server (RESEND_API_KEY not set).")
    if not to_address:
        return EmailResult(ok=False, error="No recipient email address available for this transaction.")

    from_address = os.environ.get("RESEND_FROM", DEFAULT_FROM)
    payload = json.dumps({
        "from": from_address,
        "to": [to_address],
        "subject": subject,
        "text": body,
    }).encode("utf-8")

    req = urllib.request.Request(
        RESEND_API_URL, data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
            # Resend's API sits behind Cloudflare, whose bot-protection
            # blocks Python's default urllib User-Agent (a very common,
            # well-documented false positive for legitimate API clients --
            # confirmed here as a real Cloudflare error 1010, not a Resend
            # auth/validation error).
            "User-Agent": "recovery-copilot/1.0 (+https://github.com/divyansh-3371/recovery-copilot)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if 200 <= resp.status < 300:
                return EmailResult(ok=True)
            return EmailResult(ok=False, error=f"Resend returned HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return EmailResult(ok=False, error=f"HTTP {exc.code}: {detail}")
    except Exception as exc:  # a real network failure -- surface it, don't crash the request
        return EmailResult(ok=False, error=str(exc))
