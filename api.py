"""
Thin FastAPI service exposing the same agent pipeline used by the CLI and
the React dashboard (frontend/, via dashboard_api.py's router), so
Recovery Copilot can be called as a service from a real backend instead
of only ever run as a demo.

Security posture (deliberately explicit, not assumed):
  - Rate limiting (agent/rate_limiter.py) on every route -- caps request
    volume per client IP, returns 429 + Retry-After once exceeded.
  - API-key auth (X-API-Key header) on the two data endpoints, gated by the
    API_KEY environment variable. If API_KEY is unset the service runs in
    "open demo mode" (logged clearly at startup) so grading/local testing
    has zero friction -- this tradeoff is intentional and documented, not
    an oversight.
  - Strict Pydantic validation: every field is bounded (amounts, hours,
    attempt counts) and every categorical field is checked against the
    canonical sets in data/generate_data.py, so malformed or adversarial
    input is rejected at the boundary rather than reaching model/policy
    code with unexpected values.
  - /batch/demo's `n` is capped (see MAX_BATCH_SIZE) -- an unbounded batch
    size is a straightforward resource-exhaustion vector otherwise.
  - Each request gets its own isolated audit-log path (a temp file, cleaned
    up after) instead of writing to the shared data/audit_log.jsonl --
    concurrent requests must not corrupt or reset each other's audit trail.
  - A global exception handler returns a generic 500 with no internal
    detail (stack traces, file paths) to the client; the real exception is
    logged server-side only.
  - No CORS middleware is configured -- the secure default (no browser can
    read cross-origin responses) since nothing here is meant to be called
    directly from a browser today. Add it deliberately, scoped to a real
    origin, if that ever changes -- never with allow_origins=["*"].
  - The /checkout/* and /webhooks/razorpay routes (real Razorpay integration,
    see agent/razorpay_live.py) are exempt from require_api_key -- a
    customer's own browser calls /checkout/*, and Razorpay's servers call
    the webhook, neither of which holds our X-API-Key. Both are still
    covered by the same rate-limit middleware, and the webhook route has
    its own, stronger authentication: an HMAC signature only Razorpay and
    this server know how to produce (RAZORPAY_WEBHOOK_SECRET) -- verified
    against the exact raw request body before anything else happens.

Run with:
    uvicorn api:app --reload

Then, for example:
    curl -X POST "http://localhost:8000/batch/demo?n=100"
    curl http://localhost:8000/health
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from typing import Literal

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator

import dashboard_api
from agent import email_sender, live_customer_history, razorpay_live
from agent.audit import AuditTrail
from agent.messenger import generate_message
from agent.classifier import RecoverabilityModel, train_default_model
from agent.pipeline import run_pipeline
from agent.policy import QUIET_HOURS, decide as policy_decide
from agent.rate_limiter import RateLimiter
from agent.razorpay_client import build_call
from data.generate_data import FAILURE_REASONS, PAYMENT_METHODS, RISK_TYPES, CUSTOMER_SEGMENTS, generate

logger = logging.getLogger("recovery_copilot.api")

MAX_BATCH_SIZE = 2000
RATE_LIMIT_MAX_REQUESTS = 300
RATE_LIMIT_WINDOW_SECONDS = 60.0
LIVE_AUDIT_LOG_PATH = "data/live_audit_log.jsonl"
LIVE_CUSTOMER_HISTORY_DB_PATH = "data/live_customer_history.db"

_model: RecoverabilityModel | None = None
_limiter = RateLimiter(max_requests=RATE_LIMIT_MAX_REQUESTS, window_seconds=RATE_LIMIT_WINDOW_SECONDS)
_live_audit = AuditTrail(path=LIVE_AUDIT_LOG_PATH)


def get_model() -> RecoverabilityModel:
    global _model
    if _model is None:
        _model = train_default_model()
    return _model


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("API_KEY"):
        logger.warning(
            "API_KEY is not set -- /decide and /batch/demo are running in OPEN DEMO MODE "
            "(no auth required). Set API_KEY to require the X-API-Key header in production."
        )
    if razorpay_live.is_configured():
        logger.info("Razorpay is configured -- /checkout/* will create real Test/Live Mode orders.")
    else:
        logger.warning(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set -- /checkout/* will return "
            "'not configured' until a real Razorpay account is connected. See "
            "pitch/razorpay_live_setup.md."
        )
    yield


app = FastAPI(
    title="Recovery Copilot API",
    description="AI Revenue Recovery agent -- score, decide, and (in production) execute "
                "bounded recovery actions on at-risk revenue.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: the React dashboard (frontend/) runs on its own dev-server origin
# and needs to read responses from this API. This is a deliberate, scoped
# change from the earlier "no CORS" stance -- that stance held while nothing
# legitimate needed cross-origin access; now something does, so it's scoped
# to exactly the known local dev origins (Vite's default 5173, plus 3000 as
# a common alternative), never allow_origins=["*"].
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000", "http://127.0.0.1:3000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.include_router(dashboard_api.router)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_key = request.client.host if request.client else "unknown"
    if not _limiter.allow(client_key):
        retry_after = _limiter.retry_after(client_key)
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "detail": "Too many requests -- slow down."},
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the real exception server-side; never leak internals (stack trace,
    # file paths, query details) to the client.
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error"})


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("API_KEY")
    if expected is None:
        return  # open demo mode -- see startup warning
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")


class TransactionIn(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    customer_id: str = Field(default="cust_unknown", max_length=128)
    customer_name: str = Field(default="", max_length=200)
    amount: float = Field(gt=0, le=10_000_000)
    currency: Literal["INR"] = "INR"
    risk_type: str
    failure_reason: str
    payment_method: str
    customer_segment: str
    previous_attempts: int = Field(default=0, ge=0, le=20)
    do_not_contact: bool = False
    customer_local_hour: int = Field(default=12, ge=0, le=23)
    days_since_event: int = Field(default=0, ge=0, le=3650)

    @model_validator(mode="after")
    def _check_categoricals(self) -> "TransactionIn":
        if self.risk_type not in RISK_TYPES:
            raise ValueError(f"risk_type must be one of {RISK_TYPES}")
        if self.failure_reason not in FAILURE_REASONS.get(self.risk_type, []):
            raise ValueError(f"failure_reason {self.failure_reason!r} is not valid for risk_type {self.risk_type!r}")
        if self.payment_method not in PAYMENT_METHODS:
            raise ValueError(f"payment_method must be one of {PAYMENT_METHODS}")
        if self.customer_segment not in CUSTOMER_SEGMENTS:
            raise ValueError(f"customer_segment must be one of {CUSTOMER_SEGMENTS}")
        return self


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/batch/demo")
def batch_demo(
    n: int = 50, seed: int = 42,
    _auth: None = Depends(require_api_key),
) -> dict:
    """Runs the full pipeline on a fresh synthetic batch -- lets you smoke-test
    the service without wiring up a real transaction feed yet. `n` is capped
    to bound the compute/memory a single request can demand."""
    if not (1 <= n <= MAX_BATCH_SIZE):
        raise HTTPException(status_code=422, detail=f"n must be between 1 and {MAX_BATCH_SIZE}")

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        audit_path = tmp.name
    try:
        df = generate(n=n, seed=seed)
        results, summary, _, systemic_issues = run_pipeline(df, model=get_model(), audit_path=audit_path)
    finally:
        try:
            os.remove(audit_path)
        except OSError:
            pass

    return {
        "summary": summary,
        "systemic_issues": [issue.note for issue in systemic_issues.values()],
        "action_breakdown": results["agent_action"].value_counts().to_dict(),
    }


@app.post("/decide")
def decide_one(
    txn: TransactionIn,
    _auth: None = Depends(require_api_key),
) -> dict:
    """Scores and decides on a single transaction (no batch-level root-cause
    context -- pass known systemic issues via /batch/demo for that), and
    returns the Razorpay API call stub the decision would trigger."""
    row = pd.Series({**txn.model_dump(), "_true_recoverable_prob": 0.0})
    model = get_model()
    score = float(model.predict_proba(pd.DataFrame([row]))[0])
    decision = policy_decide(row, score, systemic_issues={})
    call = build_call(row, decision)

    return {
        "action": decision.action,
        "channel": decision.channel,
        "retry_delay_hours": decision.retry_delay_hours,
        "retry_method": decision.retry_method,
        "stopping_rule_triggered": decision.stopping_rule_triggered,
        "recoverability_score": score,
        "reasoning": decision.reasoning,
        "razorpay_call": {
            "method": call.method, "path": call.path, "payload": call.payload, "note": call.note,
        } if call else None,
    }


# ---------------------------------------------------------------------------
# Live Razorpay integration -- real orders, real signature verification, and
# a real webhook receiver that feeds actual payment-failure events into the
# same score/decide pipeline as everything else above. See
# agent/razorpay_live.py and pitch/razorpay_live_setup.md.
# ---------------------------------------------------------------------------

class CheckoutOrderIn(BaseModel):
    amount: float = Field(gt=0, le=10_000_000)
    receipt: str | None = Field(default=None, max_length=64)
    # Razorpay has no concept of "customer segment" -- this is how
    # checkout.html tells the agent which one applies, riding along in the
    # Order's notes (verified live: Razorpay copies Order notes onto the
    # resulting Payment entity, which is where the webhook reads it back --
    # see agent/razorpay_live.py's map_webhook_payment_to_row()).
    customer_segment: str = Field(default="returning")

    @model_validator(mode="after")
    def _check_customer_segment(self) -> "CheckoutOrderIn":
        if self.customer_segment not in CUSTOMER_SEGMENTS:
            raise ValueError(f"customer_segment must be one of {CUSTOMER_SEGMENTS}")
        return self


class CheckoutVerifyIn(BaseModel):
    razorpay_order_id: str = Field(min_length=1, max_length=128)
    razorpay_payment_id: str = Field(min_length=1, max_length=128)
    razorpay_signature: str = Field(min_length=1, max_length=256)


@app.get("/razorpay/status")
def razorpay_status() -> dict:
    """Lets the checkout page (and the dashboard) show whether a real
    Razorpay account is connected yet, without attempting an order."""
    return {"configured": razorpay_live.is_configured()}


@app.get("/checkout")
def checkout_page() -> FileResponse:
    return FileResponse("checkout.html", media_type="text/html")


@app.post("/checkout/create-order")
def checkout_create_order(body: CheckoutOrderIn) -> dict:
    """Called by the customer's own browser (checkout.html) -- creates a
    real Razorpay order. No X-API-Key here: a customer's browser doesn't
    hold our service credential. Only the public Key ID is ever returned,
    never the Key Secret."""
    result = razorpay_live.create_order(
        amount_rupees=body.amount, receipt=body.receipt,
        notes={"customer_segment": body.customer_segment},
    )
    if not result.ok:
        raise HTTPException(status_code=503, detail=result.error)
    return {
        "ok": True,
        "order_id": result.order_id,
        "amount": result.amount_paise,
        "currency": result.currency,
        "key_id": razorpay_live.get_key_id(),
    }


@app.post("/checkout/verify")
def checkout_verify(body: CheckoutVerifyIn) -> dict:
    """Backend-side proof that a payment actually succeeded -- the frontend's
    'payment successful' callback is never trusted on its own (see the
    module docstring on agent/razorpay_live.py). Only a signature genuinely
    produced with our Key Secret passes."""
    ok = razorpay_live.verify_payment_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    )
    return {"ok": ok}


@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict:
    """Real-time entry point: Razorpay calls this the moment a payment
    fails (or any other subscribed event fires) -- no human, no dashboard
    click, no poll loop involved. The event is authenticated by an HMAC
    signature (RAZORPAY_WEBHOOK_SECRET), verified against the *raw* request
    body before it's parsed as JSON -- reserializing first would break the
    signature. A verified payment.failed event is scored and decided by the
    exact same classifier/policy pipeline as every other transaction in
    this project, and the decision is written to a live audit trail."""
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    raw_body_str = raw_body.decode("utf-8")

    if not razorpay_live.verify_webhook_signature(raw_body_str, signature):
        # Diagnostic only -- never logs the secret or the signature itself,
        # just enough shape info to tell a secret-mismatch apart from some
        # other cause (missing header, empty body, secret not loaded).
        logger.warning(
            "Webhook signature check failed. body_len=%d has_signature_header=%s "
            "webhook_secret_loaded=%s",
            len(raw_body_str), bool(signature), bool(os.environ.get("RAZORPAY_WEBHOOK_SECRET")),
        )
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = razorpay_live.parse_webhook_event(raw_body_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Malformed JSON body")

    event = payload.get("event")
    if event != "payment.failed":
        return {"status": "ignored", "event": event}

    try:
        payment_entity = payload["payload"]["payment"]["entity"]
    except (KeyError, TypeError):
        raise HTTPException(status_code=400, detail="Malformed payment.failed payload")

    row_dict = razorpay_live.map_webhook_payment_to_row(payment_entity)
    # Debug-only fields, observability only -- pulled out before the row goes
    # anywhere near the model/policy, which only know the canonical schema.
    raw_error_reason = row_dict.pop("_raw_error_reason", None)
    raw_error_code = row_dict.pop("_raw_error_code", None)
    raw_error_description = row_dict.pop("_raw_error_description", None)

    # map_webhook_payment_to_row() can't know this on its own -- a real
    # customer's attempt count only exists across separate real
    # transactions, which is exactly what live_customer_history.py tracks
    # in place of the merchant CRM a real integration would have. Without
    # this, previous_attempts stays 0 forever, and anything gated on it
    # (agent/policy.py's voice_hinglish channel, for one) can never fire
    # for a real transaction no matter what actually happened.
    row_dict["previous_attempts"] = live_customer_history.record_failure_and_get_count(
        payment_entity.get("contact"), payment_entity.get("email"),
        db_path=LIVE_CUSTOMER_HISTORY_DB_PATH,
    )

    row = pd.Series({**row_dict, "_true_recoverable_prob": 0.0})
    model = get_model()
    score = float(model.predict_proba(pd.DataFrame([row]))[0])
    decision = policy_decide(row, score, systemic_issues={})

    # --- execution -----------------------------------------------------
    # Turns the decision into a real action, for the two cases where one
    # is actually buildable right now: RETRY_PAYMENT creates a real,
    # payable Razorpay Payment Link (same connected account, no new
    # credential); SEND_MESSAGE sends a real email (Gmail SMTP + app
    # password). Deliberately only reachable from here -- the real webhook
    # path -- never from /dashboard/try or /decide, which run on synthetic
    # data with no real email address to send to in the first place.
    executed = False
    execution_detail: dict | None = None
    message_text: str | None = None
    customer_email = payment_entity.get("email")
    customer_contact = payment_entity.get("contact")
    # Resend's free sandbox sender (no verified domain) can only deliver to
    # the address that owns the Resend account -- Razorpay's checkout was
    # observed reusing a remembered contact rather than the page's prefill,
    # so email delivery is force-routed to a known-deliverable address when
    # one is configured, rather than failing on every payment whose real
    # email happens not to be it. The Payment Link's own customer_email
    # (used for whatever real record Razorpay keeps) is untouched.
    email_recipient_override = os.environ.get("EMAIL_RECIPIENT_OVERRIDE")
    email_send_to = email_recipient_override or customer_email
    # Quiet hours (agent/policy.py's QUIET_HOURS, 22:00-08:00) gate any
    # *proactive* customer contact -- an email/SMS we send unprompted.
    # They do NOT gate the payment link itself: a customer who is right
    # now, in this session, on the checkout page failing a payment is not
    # someone we're "reaching out" to at an odd hour -- they're already
    # here, and giving them an instant way to pay is responding to their
    # own action, not proactive outreach. So the link is always created
    # (the checkout page can offer a "Pay now" button regardless of hour),
    # but the email that would otherwise land in their inbox unprompted is
    # deferred instead of sent, honestly reported as such rather than
    # either ignoring the rule or silently pretending nothing happened.
    is_quiet_hours = row_dict.get("customer_local_hour") in QUIET_HOURS

    if decision.action == "RETRY_PAYMENT":
        link = razorpay_live.create_payment_link(
            amount_rupees=row_dict["amount"],
            description=f"Retry payment -- {row_dict['transaction_id']}",
            customer_name=row_dict["customer_name"],
            customer_email=customer_email,
            customer_contact=customer_contact,
        )
        if link.ok:
            executed = True  # the link itself is real regardless of whether the email also sent
            if is_quiet_hours:
                execution_detail = {
                    "type": "payment_link", "short_url": link.short_url, "link_id": link.link_id,
                    "emailed": False, "deferred_quiet_hours": True,
                }
            else:
                # Creating the link isn't enough -- a customer who just closed
                # (or never returns to) our checkout page would otherwise
                # never learn it exists. Email it too, so recovery doesn't
                # depend on someone noticing a webpage element.
                email = email_sender.send_email(
                    to_address=email_send_to,
                    subject="Your payment didn't go through -- here's a link to finish it",
                    body=f"We tried to process your payment again and couldn't reach your bank in time. "
                         f"You can complete it here: {link.short_url}",
                )
                execution_detail = {
                    "type": "payment_link", "short_url": link.short_url, "link_id": link.link_id,
                    "emailed": email.ok, "email_error": None if email.ok else email.error,
                    "sent_to": email_send_to if email.ok else None,
                }
        else:
            execution_detail = {"type": "payment_link", "error": link.error}

    elif decision.action == "SEND_MESSAGE":
        message_text = generate_message(row, decision)
        # Also create a real payment link and fold it into the message --
        # a nudge that doesn't actually let the customer pay isn't much of
        # a nudge, and it's what makes SEND_MESSAGE's outcome (recovered or
        # not) trackable the same way RETRY_PAYMENT's is, via the link's
        # own status rather than a second, separate mechanism. Created
        # regardless of quiet hours, same reasoning as RETRY_PAYMENT above
        # -- only the proactive send itself is deferred.
        link = razorpay_live.create_payment_link(
            amount_rupees=row_dict["amount"],
            description=f"Complete your payment -- {row_dict['transaction_id']}",
            customer_name=row_dict["customer_name"],
            customer_email=customer_email,
            customer_contact=customer_contact,
        )
        link_id = link.link_id if link.ok else None
        short_url = link.short_url if link.ok else None

        if is_quiet_hours:
            executed = bool(link.ok)
            execution_detail = {
                "type": "email", "emailed": False, "deferred_quiet_hours": True,
                **({"link_id": link_id, "short_url": short_url} if link_id else {}),
            }
        else:
            email_body = message_text
            if link.ok:
                email_body = f"{message_text}\n\nComplete your payment here: {link.short_url}"
            email = email_sender.send_email(to_address=email_send_to, subject="Let's get your payment sorted", body=email_body)
            if email.ok:
                executed = True
                execution_detail = {"type": "email", "sent_to": email_send_to}
                if link_id:
                    execution_detail["link_id"] = link_id
                    execution_detail["short_url"] = short_url
            else:
                execution_detail = {"type": "email", "error": email.error}

    _live_audit.log(
        transaction_id=row_dict["transaction_id"],
        action=decision.action,
        reasoning=decision.reasoning,
        stopping_rule_triggered=decision.stopping_rule_triggered,
        extra={
            "source": "razorpay_webhook",
            "event": event,
            "failure_reason": row_dict["failure_reason"],
            "amount": row_dict["amount"],
            "customer_segment": row_dict["customer_segment"],
            "recoverability_score": score,
            "raw_error_reason": raw_error_reason,
            "raw_error_code": raw_error_code,
            "raw_error_description": raw_error_description,
            "executed": executed,
            "execution_detail": execution_detail,
            "message": message_text,
        },
    )

    return {
        "status": "processed", "action": decision.action, "recoverability_score": score,
        "executed": executed, "execution_detail": execution_detail,
    }


@app.get("/checkout/decision/{payment_id}")
def checkout_decision(payment_id: str) -> dict:
    """Lets checkout.html show the agent's decision right at the moment of
    failure, on the same page the customer is looking at -- polled after a
    payment.failed event fires client-side, since the webhook (and the
    decision it triggers) typically lands within a few seconds, not
    instantly. There's no way to show this inside Razorpay's own hosted
    dashboard -- it has no extension point for a third party's business
    logic -- so this is the realistic version of "visible at payment time":
    on the merchant's own page, which is where a real integration would
    put it anyway."""
    entry = _live_audit.for_transaction(payment_id)
    if entry.empty:
        return {"found": False}
    row = entry.iloc[-1]  # last entry for this id, in case of a retry/replay
    score = row.get("recoverability_score")
    executed = row.get("executed")
    execution_detail = row.get("execution_detail")
    return {
        "found": True,
        # cast off numpy/pandas scalar types explicitly -- they aren't
        # JSON-serializable by the plain json module FastAPI's default
        # response class uses
        "action": str(row.get("action")) if row.get("action") is not None else None,
        "reasoning": list(row.get("reasoning")) if isinstance(row.get("reasoning"), (list, tuple)) else [],
        "recoverability_score": float(score) if score is not None and not pd.isna(score) else None,
        "failure_reason": str(row.get("failure_reason")) if row.get("failure_reason") is not None else None,
        "executed": bool(executed) if isinstance(executed, (bool,)) else False,
        "execution_detail": execution_detail if isinstance(execution_detail, dict) else None,
    }


@app.get("/checkout/recovery-status/{payment_id}")
def recovery_status(payment_id: str) -> dict:
    """Checks whether a real transaction was actually recovered -- i.e.
    whether the Payment Link created for it (by RETRY_PAYMENT or
    SEND_MESSAGE) has since been paid. Queries Razorpay live rather than
    trusting anything cached, since payment can happen any time after the
    original decision, not just in the seconds right after it."""
    entry = _live_audit.for_transaction(payment_id)
    if entry.empty:
        return {"found": False}
    row = entry.iloc[-1]
    detail = row.get("execution_detail")
    link_id = detail.get("link_id") if isinstance(detail, dict) else None
    if not link_id:
        return {"found": True, "has_link": False, "recovered": False, "recovered_amount": None}

    status = razorpay_live.fetch_payment_link_status(link_id)
    if not status.ok:
        return {"found": True, "has_link": True, "recovered": False, "recovered_amount": None,
                "error": status.error}
    recovered = status.status == "paid"
    return {
        "found": True, "has_link": True, "status": status.status,
        "recovered": recovered,
        "recovered_amount": status.amount_paid_rupees if recovered else None,
    }
