"""
Generates the actual customer-facing recovery message for a decision.

Uses the Anthropic API (Claude) when ANTHROPIC_API_KEY is set in the
environment, for a genuinely personalized message tuned to failure reason,
channel, and tone. Falls back to a clean deterministic template otherwise, so
the pipeline and dashboard never break in an offline/no-key demo environment.

Tone escalates with contact attempt (row["previous_attempts"]): a first
contact is warm and low-pressure, a second is a polite follow-up, a third is
a final, more direct reminder -- still professional, never aggressive, but a
customer contacted three times should be able to tell that apart from the
first message. Capped at tier 2 (attempts >= 2) since the policy engine's
MAX_ATTEMPTS stopping rule means a message is never sent past that anyway.

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

# tier 0 = first contact, 1 = follow-up, 2 = final reminder (capped -- a
# message is never sent at previous_attempts >= MAX_ATTEMPTS, so 2 is the
# real ceiling here regardless of how high previous_attempts could go)
_MAX_TIER = 2


def _urgency_tier(previous_attempts: int) -> int:
    return min(max(int(previous_attempts), 0), _MAX_TIER)


_TONE_LABEL = {0: "first contact — warm, low-pressure", 1: "a polite follow-up reminder",
               2: "a final reminder — more direct and time-bound, still professional, never aggressive"}

_DEFAULT_TEMPLATES = {
    "en": {
        0: "Hi {name}, your ₹{amount} payment didn't go through because {reason}. "
           "You can complete it again here — takes less than 30 seconds!",
        1: "Hi {name}, just a quick follow-up — your ₹{amount} payment is still pending because {reason}. "
           "It only takes a moment to finish it off here.",
        2: "Hi {name}, this is a final reminder — your ₹{amount} payment still hasn't gone through "
           "({reason}). Please complete it soon so we can avoid any interruption to your service.",
    },
    "hi": {
        0: "Namaste {name}, aapka ₹{amount} ka payment complete nahi ho paya kyunki {reason}. "
           "Aap yahan click karke dobara try kar sakte hain — bas 30 second lagenge!",
        1: "Namaste {name}, ek chhota sa reminder — aapka ₹{amount} ka payment abhi bhi pending hai "
           "kyunki {reason}. Bas ek minute mein complete ho jayega, yahan click karein.",
        2: "Namaste {name}, yeh ek final reminder hai — aapka ₹{amount} ka payment abhi tak complete "
           "nahi hua ({reason}). Kripya jaldi complete karein taaki koi rukawat na ho.",
    },
}

_INVOICE_TEMPLATES = {
    "en": {
        0: "Hi {name}, {reason} for your ₹{amount} invoice. Please settle it at your earliest to "
           "avoid a late fee. Thank you!",
        1: "Hi {name}, following up on your ₹{amount} invoice — {reason}. A quick settlement would "
           "really help us close this out.",
        2: "Hi {name}, this is a final reminder that your ₹{amount} invoice is still unpaid ({reason}). "
           "Please settle it as soon as possible to avoid a late fee or further escalation.",
    },
    "hi": {
        0: "Namaste {name}, aapka invoice ₹{amount} ka {reason}. Kripya jaldi se payment complete kar "
           "dijiye taaki koi late fee na lage. Dhanyawad!",
        1: "Namaste {name}, aapke ₹{amount} invoice ke baare mein follow-up kar rahe hain — {reason}. "
           "Jald settle karne se humein bahut madad milegi.",
        2: "Namaste {name}, yeh final reminder hai ki aapka ₹{amount} invoice abhi tak unpaid hai "
           "({reason}). Kripya jald se jald settle karein taaki late fee ya further escalation na ho.",
    },
}


def _template_message(row: pd.Series, decision: Decision, hinglish: bool = False) -> str:
    reason_txt = REASON_PHRASING.get(row["failure_reason"], "there was an issue with your last payment")
    name = row.get("customer_name", "there")
    first_name = str(name).split(" ")[0] if name else "there"
    amount = row["amount"]
    tier = _urgency_tier(row.get("previous_attempts", 0))
    lang = "hi" if hinglish else "en"

    table = _INVOICE_TEMPLATES if row["risk_type"] == "invoice_overdue" else _DEFAULT_TEMPLATES
    return table[lang][tier].format(name=first_name, amount=f"{amount:,.0f}", reason=reason_txt)


def generate_message(row: pd.Series, decision: Decision) -> str:
    hinglish = decision.channel == "voice_hinglish"
    client = _get_client()
    if client is None:
        return _template_message(row, decision, hinglish=hinglish)

    tier = _urgency_tier(row.get("previous_attempts", 0))
    language_instr = "in casual Hinglish (Roman script, mixing Hindi and English as urban Indian customers text/speak)" \
        if hinglish else "in friendly, concise English"
    prompt = (
        f"Write a single short (2-3 sentence) payment recovery message for a customer, {language_instr}. "
        f"Context: risk_type={row['risk_type']}, failure_reason={row['failure_reason']}, "
        f"amount=INR {row['amount']:.0f}, customer_segment={row['customer_segment']}, "
        f"channel={decision.channel}. "
        f"This is contact attempt #{tier + 1} for this customer on this issue — tone should be "
        f"{_TONE_LABEL[tier]}. Include a clear next step. "
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
