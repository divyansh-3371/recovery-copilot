"""
Real email delivery for the SEND_MESSAGE action, via Gmail SMTP + an app
password -- this is what turns a generated message from text into an
actual delivered nudge for a real (live-webhook-driven) transaction.

Deliberately NOT wired into the synthetic pipeline (data/generate_data.py
never generates an email address at all -- see its customer_name-only
Faker call) -- this module is only ever called from api.py's real webhook
handler, never from /dashboard/try or /decide, so a demo run of the
synthetic batch can never accidentally email a real person.

Configuration, via environment variables, never hardcoded or logged:
    GMAIL_USER          -- the Gmail address to send from
    GMAIL_APP_PASSWORD   -- an App Password (not the account password) --
                            generated at https://myaccount.google.com/apppasswords,
                            requires 2-Step Verification enabled first

If unset, send_email() returns a clear "not configured" result instead of
raising, same degrade-gracefully pattern as agent/razorpay_live.py.
"""
from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


@dataclass
class EmailResult:
    ok: bool
    error: str | None = None


def is_configured() -> bool:
    return bool(os.environ.get("GMAIL_USER")) and bool(os.environ.get("GMAIL_APP_PASSWORD"))


def send_email(to_address: str, subject: str, body: str) -> EmailResult:
    user = os.environ.get("GMAIL_USER")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not app_password:
        return EmailResult(ok=False, error="Email is not configured on this server "
                                            "(GMAIL_USER / GMAIL_APP_PASSWORD not set).")
    if not to_address:
        return EmailResult(ok=False, error="No recipient email address available for this transaction.")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_address

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(user, app_password)
            server.sendmail(user, [to_address], msg.as_string())
        return EmailResult(ok=True)
    except Exception as exc:  # a real SMTP/network failure -- surface it, don't crash the request
        return EmailResult(ok=False, error=str(exc))
