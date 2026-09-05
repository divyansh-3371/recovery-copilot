# Recovery Copilot

**Track:** AI Revenue Recovery — Razorpay AI Buildathon 2026

An agent that detects revenue at risk (failed payments, checkout abandonment,
subscription/mandate failures, overdue B2B invoices), decides the right
*bounded* intervention, and executes it — with measured recovered ₹, a
compliant stopping-rules policy, and a complete audit trail.

The dashboard's **"Try a transaction" tab** lets you feed the agent your own
transaction (amount, failure reason, payment method, attempts...) and
watch the score, decision, reasoning, cost, and Razorpay-call mapping
recompute in real time — nothing on this dashboard is pre-baked.

## The Bar this project targets

| Requirement | Where it's satisfied |
|---|---|
| Demonstrate measured money recovered from a batch of transactions | `agent/simulator.py` runs the agent's decisions *and* a naive baseline over the same batch and reports the real ₹ delta — see the dashboard's KPI row |
| Compliant escalation procedures with stopping rules | `agent/policy.py` — do-not-contact, max-attempt cap, uneconomical-amount floor, quiet-hours deferral, all checked before any customer-facing action |
| Complete audit trail for all actions | `agent/audit.py` — one JSON line per decision, with full reasoning, written to `data/audit_log.jsonl` |
| Move beyond detection to actual recovery execution | The policy engine doesn't just flag risk — it picks a concrete action (`RETRY_PAYMENT`, `SEND_MESSAGE`, `ESCALATE_HUMAN`, `ESCALATE_COLLECTIONS`, `ESCALATE_OPS`, `STOP`) and the simulator resolves its real outcome |

## Coverage of the track's example directions

| Direction | Status | Where |
|---|---|---|
| Payment degradation → root cause → recovery action | ✅ | `agent/root_cause.py` + `ESCALATE_OPS` |
| Checkout drop-off recovery | ✅ | `risk_type=checkout_abandonment` |
| Failed-subscription recovery | ✅ | `risk_type=subscription_failure` |
| B2B receivables chaser | ✅ | `risk_type=invoice_overdue` |
| Mandate retry sequencer | ✅ | `agent/retry_sequencer.py` — explicit multi-step sequence, not a single blind retry |
| Hinglish voice recovery | ✅ | `agent/messenger.py` — offline TTS |
| Promise-to-pay tracker | ✅ | `agent/promise_tracker.py` — classifies kept/broken, auto-escalates broken promises |

## Architecture

```
data/generate_data.py  →  synthetic batch of at-risk revenue events
                              │
                              ▼
        agent/pipeline.py  (orchestrator)
        ┌─────────────────────────────────────────────────────┐
        │ 1. classifier.py  → sklearn logistic-regression      │
        │    recoverability score, trained on simulated        │
        │    historical outcomes; explainable per-transaction  │
        │                                                       │
        │ 2. root_cause.py → portfolio-level anomaly detector: │
        │    flags (payment_method, failure_reason) combos     │
        │    running hot vs their own baseline (infra outages) │
        │                                                       │
        │ 3. policy.py     → decision engine + stopping rules  │
        │    picks one bounded action per transaction           │
        │                                                       │
        │ 4. messenger.py  → Claude-generated (or template)     │
        │    recovery message; Hinglish + offline TTS for the  │
        │    voice_hinglish channel                             │
        │                                                       │
        │ 5. audit.py      → append-only reasoning trail        │
        └─────────────────────────────────────────────────────┘
                              │
                              ▼
        6. simulator.py → resolves agent outcome vs a naive
           baseline policy on the same batch → measured ₹ delta
                              │
                              ▼
        dashboard_api.py (FastAPI router)  →  frontend/ (React dashboard)
```

See `pitch/architecture.md` for the fuller write-up.

## Gaps found on a code-level re-review, and how each was closed

A later pass re-checked the actual code (not the intended design) against
five specific criteria: a config-driven failure taxonomy, time-aware retry
logic, guardrails, audit-trail completeness, and the proof layer's cost
accounting. Two were solid as-is; three had real gaps, closed additively
(nothing removed, see `pitch/build_challenges.md` #10 for the full log):

- **Failure taxonomy was hardcoded, not a config table** — `agent/decision_table.py`
  is now the single source of truth (category, blind-retry-effectiveness,
  mandate flag, tuned first-retry delay) that `policy.py`, `retry_sequencer.py`,
  and `simulator.py` all read from, instead of three separately-hardcoded,
  drifting sets. Also added the missing **`risk_block`** failure reason
  (a risk/fraud-engine decline) — routed to `ESCALATE_HUMAN` only, **never**
  auto-retried or messaged, since retrying past a risk block is itself a
  compliance risk.
- **Retry timing lost failure-reason granularity in an earlier refactor** —
  restored: a transient infra blip (bank timeout) retries in 30 minutes: an
  insufficient-funds failure waits 24h for a balance/salary cycle, pulled
  from the same decision table.
- **Idempotency/cancellation was missing** — `agent/workflow.py` now checks,
  *before* deciding each day's action, whether the customer already paid
  through a channel the agent never touched, and if so cancels all
  remaining scheduled actions with an explicit `IDEMPOTENT_CANCEL` audit
  entry, rather than continuing to retry/message someone who's already paid.
- **Audit trail didn't log `failure_reason` or outcome** — both decision-time
  and outcome-time entries now carry `failure_reason`, and every decision
  gets a follow-up `OUTCOME_RESOLVED`/`OUTCOME_UNRESOLVED` entry once its
  result is known.
- **Cost of intervention was missing from the proof layer** — `agent/cost_model.py`
  estimates a per-action cost (SMS vs. voice vs. a human agent's time vs. a
  gateway retry); the dashboard and `summarize()` now report **net**
  recovered (gross minus cost) for both the agent and the baseline, not
  just gross ₹.

## Cost-aware value triage

Above `VALUE_TRIAGE_THRESHOLD` (₹75,000, in `agent/policy.py`), any
transaction routes to `ESCALATE_HUMAN` **regardless of what its
failure-reason category would otherwise pick** — a ₹1,50,000 expired-card
failure gets a human, not the usual "ask the customer to update their
card" message; a ₹50 one still gets the cheap automated path. Checked
after every compliance-critical rule (do-not-contact, the max-attempt cap,
systemic-issue/ops routing, a risk-engine block) so none of those are ever
overridden by value — only the routine reason-based branches are. Try it
on the dashboard's **Try a transaction** tab: push the amount past ₹75,000 on
any failure reason and watch the decision flip.

## Beyond the single-pass MVP

Four additions push this past a one-shot demo toward something that argues
for itself as production-minded:

- **`agent/razorpay_client.py`** — maps every bounded action to the Razorpay
  API call it would actually trigger (Payment Links create+notify, a fresh
  Order for a scheduled retry, an internal ops-alert route for systemic
  issues) — stubbed, no live calls, but shown live in the dashboard's
  drill-down so it's clear this isn't operating in the abstract.
- **`agent/workflow.py` + `agent/state_store.py`** — a multi-day, *stateful*
  simulation (SQLite-backed) proving "executes a bounded recovery workflow"
  means more than a single decision: the retry sequencer genuinely advances
  step by step across simulated days, and a promise-to-pay deadline
  genuinely arrives and gets checked. See the dashboard's "Multi-day
  workflow simulation" section, or run `python simulate_workflow.py`.
- **`tests/` (127 tests) + `.github/workflows/tests.yml`** — the stopping
  rules, the root-cause detector, the retry sequencer, the promise tracker,
  the simulator's uplift math, and the workflow's state machine all have
  tests; CI runs them on every push.
- **`api.py`** — the same pipeline exposed as a FastAPI service
  (`/decide`, `/batch/demo`), so it's callable from a real backend, not only
  runnable as a CLI or through the dashboard. Hardened, not just functional:
  rate limiting, SQL-injection-defended state persistence, strict input
  validation, bounded batch size, opt-in API-key auth, and no internal
  detail leaked on error — every control verified against a live server,
  not just asserted. See `pitch/security.md` for the full rundown.

## Real Razorpay integration (Test Mode)

Beyond `agent/razorpay_client.py`'s illustrative call-shape mapping, this
project also has a **real** integration, built against the official
`razorpay` Python SDK — not a mock:

- **`agent/razorpay_live.py`** — creates real Razorpay orders, verifies a
  payment's signature on the *backend* before ever trusting a "success"
  callback from the browser (a frontend-only success is easy to fake — the
  signature check is what actually proves the payment happened), and
  verifies real webhook signatures (HMAC-SHA256 against the raw request
  body, using `hmac.compare_digest`-based comparison inside the SDK).
- **`checkout.html` + `api.py`'s `/checkout/create-order` and
  `/checkout/verify`** — a real Razorpay Checkout flow: the frontend only
  ever sees the public Key ID, the backend holds the Key Secret and does
  the signature verification.
- **`api.py`'s `/webhooks/razorpay`** — the actual real-time path: when a
  real Razorpay payment fails, Razorpay's servers call this endpoint
  directly (no dashboard click, no polling), and a verified event is
  scored and decided by the *exact same* classifier/policy pipeline used
  everywhere else in this project, then written to `data/live_audit_log.jsonl`.
  This is what makes the earlier "is it doing real-time processing"
  question concretely true once a Razorpay account is connected, rather
  than only true of the synthetic-batch pipeline.
- **The dashboard's `🔴 Live` tab** — reads `data/live_audit_log.jsonl` and
  shows every real transaction Razorpay has actually sent, in the same
  plain-language style as the rest of the dashboard (amount, reason,
  customer type, action, confidence, reasoning), not just a JSON file to
  grep through.
- **Customer type on checkout** — `checkout.html` asks (new/returning/VIP),
  passed through as a Razorpay Order note and read back off the resulting
  Payment on the webhook side (`agent/razorpay_live.py`) — verified live
  that Razorpay actually carries Order notes through to the Payment entity,
  since that isn't clearly documented anywhere. Without this, every real
  transaction would score as if the customer were anonymous, since Razorpay
  itself has no concept of customer segment.

Fully covered by tests that don't need live credentials — the signature
math is the same HMAC-SHA256 Razorpay's SDK uses internally, so
`tests/test_razorpay_live.py` constructs real valid/tampered signatures
itself and proves the wrapper accepts/rejects them correctly;
`tests/test_razorpay_webhook_api.py` drives a genuinely-signed
`payment.failed` webhook through the live FastAPI app end-to-end and
checks the resulting decision and audit entry. The one thing that
genuinely can't be tested without a live account is the outbound
`order.create()` HTTP call itself — see **`pitch/razorpay_live_setup.md`**
for the ~10-minute account setup (Test Mode keys, an `ngrok` tunnel,
webhook registration) that turns this on for real, plus what it does and
doesn't prove.

## Tech stack

Python backend: `pandas` / `numpy` for data, `scikit-learn` for the
recoverability model, `anthropic` (optional, with a graceful template
fallback) for message generation, `pyttsx3` for fully offline
text-to-speech on the Hinglish voice channel, `sqlite3` (stdlib) for
workflow state, `pytest` for tests, `fastapi`/`uvicorn` for the API +
dashboard-data service, `razorpay` (official SDK) for real order
creation and signature verification. React frontend: Vite + React,
`recharts` for charts, plain CSS.

## Running it

```bash
pip install -r requirements.txt

# CLI: runs the full pipeline on a fresh synthetic batch, prints the summary
python run_batch.py

# Multi-day stateful workflow simulation
python simulate_workflow.py --days 5

# Test suite
pytest -q

# API + dashboard-data service
uvicorn api:app --port 8010 --reload

# React dashboard (separate terminal)
cd frontend && npm install && npm run dev
# open http://localhost:5173

# Real Razorpay checkout, once configured (see pitch/razorpay_live_setup.md)
# open http://localhost:8010/checkout
```

Optional: set `ANTHROPIC_API_KEY` in your environment for LLM-generated
recovery messages; without it, the messenger falls back to a clean
deterministic template so the demo never breaks. Optional: set
`RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` / `RAZORPAY_WEBHOOK_SECRET` to
turn on the real Razorpay checkout + webhook path (`pitch/razorpay_live_setup.md`);
without them, `/checkout/*` clearly reports "not configured" and nothing
else in the app changes.

## What's real vs. simulated

This is a buildathon MVP, built honestly:
- **Real:** the trained classifier, the decision/policy engine, the stopping
  rules, the audit trail, the root-cause anomaly detector, the LLM message
  generation, the offline TTS, the multi-day state machine, the test suite,
  the API service.
- **Also real, when a Razorpay account is connected (`agent/razorpay_live.py`,
  see the section above):** order creation, backend payment-signature
  verification, and webhook-signature-verified real-time processing of
  actual `payment.failed` events through the real classifier/policy
  pipeline. This is opt-in — with no `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`/
  `RAZORPAY_WEBHOOK_SECRET` set, `/checkout/*` clearly reports "not
  configured" and every test/demo path above still works unchanged.
- **Simulated:** the batch transaction data and whether an intervention
  "succeeds" — both come from `data/generate_data.py`, which encodes a hidden
  ground-truth recoverability prior never seen by the agent, used only by
  `agent/simulator.py` (and `agent/workflow.py`, day by day) to resolve
  realistic outcomes. In production this batch would be a merchant's real
  failed-transaction feed and the training data would be their real
  resolved-case history.
- **Still a stub, deliberately:** `agent/razorpay_client.py` maps a
  *decision* (`RETRY_PAYMENT`, `SEND_MESSAGE`, ...) to the Razorpay API call
  it would trigger, for the dashboard's drill-down — it shows the call
  shape but doesn't fire it. The live webhook path above decides in real
  time; actually executing that decision (firing a real retry, sending a
  real SMS) is the natural next step once retry/notification credentials
  are also in place — see the "Not yet built" note in
  `pitch/razorpay_live_setup.md`.

## Project structure

```
data/generate_data.py     synthetic batch generator (+ injected outage)
agent/features.py         shared feature engineering
agent/classifier.py       recoverability model (train + explain)
agent/decision_table.py   single-source-of-truth failure-reason -> category/retry/cost mapping
agent/root_cause.py       portfolio-level degradation detector
agent/retry_sequencer.py  explicit mandate/payment retry sequence (reason-tuned first step)
agent/promise_tracker.py  promise-to-pay classification
agent/cost_model.py       estimated cost per intervention action
agent/policy.py           decision engine + stopping rules
agent/messenger.py        message generation (LLM + template, tone escalates with attempt #) + offline TTS
agent/razorpay_client.py  action -> Razorpay API call stub mapping (illustrative, no network)
agent/razorpay_live.py    real Razorpay SDK wrapper: orders, payment links, signature verification
agent/email_sender.py     real email delivery (Resend HTTP API) for SEND_MESSAGE/RETRY_PAYMENT
agent/audit.py            append-only audit trail
agent/simulator.py        outcome simulation + baseline comparison + net-recovered math
agent/state_store.py      SQLite persistence for the multi-day workflow
agent/workflow.py         multi-day stateful workflow orchestrator + idempotency guardrail
agent/pipeline.py         single-pass orchestrator
run_batch.py              CLI: single-pass batch run
simulate_workflow.py      CLI: multi-day workflow simulation
api.py                    FastAPI service (/decide, /batch/demo, /checkout/*, /webhooks/razorpay)
dashboard_api.py          FastAPI router: JSON data endpoints for the React dashboard
frontend/                 React dashboard (Vite) -- Dashboard, Transactions, Timeline, Try, Live tabs
checkout.html             real Razorpay Checkout frontend (served at GET /checkout)
tests/                    pytest suite (144 tests)
.github/workflows/        CI: runs the test suite on every push
pitch/                    architecture doc, pitch script, build-challenges log, live-Razorpay setup guide
```

## Build challenges & how they were resolved

See `pitch/build_challenges.md` for the full log — this is also the source
for the submission form's "Build Challenges & Technical Obstacles" field.
