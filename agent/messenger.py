"""
Generates the actual customer-facing recovery message for a decision.

Uses the Anthropic API (Claude) when ANTHROPIC_API_KEY is set in the
environment, for a genuinely personalized message tuned to failure reason,
channel, and tone. Falls back to a clean deterministic template otherwise, so
the pipeline and dashboard never break in an offline/no-key demo environment.

Also provides on-demand offline text-to-speech (pyttsx3, no internet needed)
for the "voice_hinglish" channel, used by the dashboard to actually play the
message the agent would call/say — this is generated on demand for a single
selected transaction, not for the whole batch, to keep batch runs fast.
"""
from __future__ import annotations

import os

import pandas as pd

from agent.policy import Decision

_anthropic_client = None


def _get_client():
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic

        _anthropic_client = anthropic.Anthropic(api_key=api_key)
        return _anthropic_client
    except Exception:
        return None


REASON_PHRASING = {
    "insufficient_funds": "it looks like the balance was a little short",
    "bank_timeout": "your bank's server didn't respond in time",
    "card_expired": "your card on file has expired",
    "wrong_cvv": "the card details didn't match",
    "network_drop": "the connection dropped mid-payment",
    "issuer_declined": "your bank declined the transaction",
    "cart_abandoned_otp": "the OTP step wasn't completed",
    "cart_abandoned_payment_page": "the payment page wasn't finished",
    "price_hesitation": "checkout wasn't completed",
    "mandate_expired": "your auto-pay mandate has expired",
    "mandate_insufficient_funds": "the auto-pay attempt found insufficient balance",
    "mandate_bank_error": "your bank's mandate system had an error",
    "invoice_overdue_15d": "the invoice is now 15 days overdue",
    "invoice_overdue_30d": "the invoice is now 30 days overdue",
    "invoice_overdue_45plus": "the invoice is significantly overdue",
}


def _template_message(row: pd.Series, decision: Decision, hinglish: bool = False) -> str:
    reason_txt = REASON_PHRASING.get(row["failure_reason"], "there was an issue with your last payment")
    name = row.get("customer_name", "there")
    first_name = str(name).split(" ")[0] if name else "there"
    amount = row["amount"]

    if row["risk_type"] == "invoice_overdue":
        if hinglish:
            return (f"Namaste {first_name}, aapka invoice ₹{amount:,.0f} ka {reason_txt}. "
                     f"Kripya jaldi se payment complete kar dijiye taaki koi late fee na lage. Dhanyawad!")
        return (f"Hi {first_name}, {reason_txt} for your ₹{amount:,.0f} invoice. "
                f"Please settle it at your earliest to avoid a late fee. Thank you!")

    if hinglish:
        return (f"Namaste {first_name}, aapka ₹{amount:,.0f} ka payment complete nahi ho paya kyunki {reason_txt}. "
                 f"Aap yahan click karke dobara try kar sakte hain — bas 30 second lagenge!")
    return (f"Hi {first_name}, your ₹{amount:,.0f} payment didn't go through because {reason_txt}. "
            f"You can complete it again here — takes less than 30 seconds!")


def generate_message(row: pd.Series, decision: Decision) -> str:
    hinglish = decision.channel == "voice_hinglish"
    client = _get_client()
    if client is None:
        return _template_message(row, decision, hinglish=hinglish)

    language_instr = "in casual Hinglish (Roman script, mixing Hindi and English as urban Indian customers text/speak)" \
        if hinglish else "in friendly, concise English"
    prompt = (
        f"Write a single short (2-3 sentence) payment recovery message for a customer, {language_instr}. "
        f"Context: risk_type={row['risk_type']}, failure_reason={row['failure_reason']}, "
        f"amount=INR {row['amount']:.0f}, customer_segment={row['customer_segment']}, "
        f"channel={decision.channel}. Be warm, not pushy, and include a clear next step. "
        f"Return only the message text, no preamble."
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text")).strip()
        return text or _template_message(row, decision, hinglish=hinglish)
    except Exception:
        return _template_message(row, decision, hinglish=hinglish)


def synthesize_voice(text: str, out_path: str) -> bool:
    """Offline TTS via pyttsx3. Returns True on success, False if unavailable
    (e.g. no audio backend in the environment) — caller should degrade
    gracefully (show text only) if this returns False."""
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.save_to_file(text, out_path)
        engine.runAndWait()
        return os.path.exists(out_path)
    except Exception:
        return False
