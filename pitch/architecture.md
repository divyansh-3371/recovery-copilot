# Architecture — Recovery Copilot

## Problem framing

Revenue loss at a payments company rarely happens in one clean step: a
payment degrades, a checkout gets abandoned, a subscription mandate fails, or
a B2B invoice goes overdue. Each of these is usually handled — if at all —
as an isolated, undifferentiated event: log it, maybe fire one generic
retry. Recovery Copilot closes the loop: detect the at-risk revenue,
diagnose *why* it's at risk (including whether it's the customer's fault at
all), choose the cheapest intervention that will actually work, execute it,
and prove — with real numbers — that it recovered more than doing nothing
smarter would have.

## Data flow

```
data/generate_data.py
   │  synthetic batch: payment_failure / checkout_abandonment /
   │  subscription_failure / invoice_overdue events, each with a hidden
   │  ground-truth recoverability prior the agent never sees
   ▼
agent/pipeline.py  (orchestrator — run_pipeline())
   │
   ├─ 1. agent/classifier.py
   │     RecoverabilityModel: one-hot + scaled-numeric features through a
   │     scikit-learn LogisticRegression, trained on a separately-seeded
   │     simulated "historical" batch (3000 resolved-outcome events).
   │     .predict_proba() scores the live batch; .explain() decomposes any
   │     single row's score into its top signed feature contributions
   │     (coefficient × scaled value) — the dashboard surfaces this as
   │     "why the agent thinks this," so the score is never a black box.
   │
   ├─ 2. agent/root_cause.py
   │     detect_systemic_issues(): groups the batch by
   │     (payment_method, failure_reason), compares each group's last-24h
   │     rate to its own older baseline rate, and flags combinations
   │     running significantly hot as likely infrastructure degradation
   │     rather than customer-side failure. This directly implements
   │     Razorpay's suggested "payment degradation root-cause analyzer"
   │     direction, and it's consulted before any retry decision.
   │
   ├─ 3. agent/policy.py
   │     decide(row, score, systemic_issues) → a Decision. Stopping rules
   │     are checked FIRST, in priority order, before any customer-facing
   │     action can be chosen:
   │       1. do_not_contact flag set → STOP
   │       2. previous_attempts >= cap (3) → STOP
   │       3. amount below the recovery-cost floor → STOP
   │       4. (method, reason) flagged as a systemic issue → ESCALATE_OPS,
   │          not a customer retry/message
   │       5. otherwise, score-driven routing to RETRY_PAYMENT /
   │          SEND_MESSAGE / ESCALATE_HUMAN, with a quiet-hours check that
   │          defers (never cancels) customer contact
   │     Every branch attaches a human-readable reasoning string.
   │
   ├─ 4. agent/messenger.py
   │     Builds the actual customer-facing text for SEND_MESSAGE actions.
   │     Uses the Anthropic API when ANTHROPIC_API_KEY is set (tuned by
   │     failure reason, channel, and tone); otherwise a clean deterministic
   │     template, so the pipeline never breaks offline. The voice_hinglish
   │     channel additionally gets a fully offline TTS render via pyttsx3
   │     (SAPI5 on Windows) — synthesized on demand for one transaction at
   │     a time, not for the whole batch, to keep batch runs fast.
   │
   └─ 5. agent/audit.py
         AuditTrail.log() appends one JSON line per decision — trace_id,
         transaction_id, timestamp, action, full reasoning list, which
         stopping rule (if any) fired, which systemic issue (if any) applied
         — to data/audit_log.jsonl. Nothing the agent does is unlogged.
   │
   ▼
agent/simulator.py
   simulate_batch(): resolves whether each transaction's chosen
   intervention actually recovers the money, using the hidden ground-truth
   prior modulated by how well-matched the intervention is (e.g. blindly
   retrying a card that needs updating is heavily penalized; a human
   escalation on a high-value account is boosted). In parallel, it runs a
   naive BASELINE policy over the identical batch — a single blind
   retry/reminder for everyone, no stopping rules, no root-cause awareness
   — so the recovered-₹ comparison is a real, measured delta, and it also
   surfaces how many compliance violations (contacting do-not-contact
   customers, exceeding the attempt cap) the baseline would have committed
   that Recovery Copilot avoided.
   │
   ▼
dashboard_api.py (FastAPI router) → frontend/ (React + recharts dashboard)
   KPI row (stat tiles) → bar chart (recovered: baseline vs agent,
   per risk type) → action-breakdown bar → filterable transaction table →
   single-transaction drill-down (score explanation, decision reasoning,
   generated message, full audit trail) → Live tab (real Razorpay checkout,
   real-time webhook-driven decisions, real execution).
```

## Two directions added after re-checking against the track spec

Re-reading Razorpay's exact track text (example directions + "the bar")
surfaced two named directions that weren't explicit yet:

- **`agent/retry_sequencer.py`** — the "mandate retry sequencer" direction.
  Retry timing/method had been inline, ad-hoc logic inside `policy.py`;
  it's now a named, explicit multi-step sequence (immediate → delayed →
  fallback method / manual re-authorization link) for both plain payment
  retries and subscription mandates specifically.
- **`agent/promise_tracker.py`** — the "promise-to-pay tracker" direction,
  which didn't exist at all. For overdue invoices and failed subscriptions
  where the customer is messaged, it classifies whether a promise to pay
  was made and whether it was kept — reusing the batch's own resolved
  outcome as ground truth rather than a second independent coin flip, so
  it can never contradict the recovered-₹ numbers — and a broken promise
  triggers its own audit-logged escalation instead of silently dropping.

## Four additions past the single-pass MVP

With more runway than the initial build assumed, four more things were
added specifically to close the gap between "a working demo" and "something
that argues for itself as production-minded":

- **`agent/razorpay_client.py`** maps every bounded action to the Razorpay
  API call it would actually make (Payment Links create+notify for
  `SEND_MESSAGE`, a fresh Order for a scheduled `RETRY_PAYMENT`, an internal
  ops-alert route for `ESCALATE_OPS`). These are stubs — no live calls, no
  credentials — deliberately hedged in their own docstrings as illustrative
  of integration shape rather than pixel-perfect API accuracy, since getting
  a real platform's own API subtly wrong in front of that platform's
  engineers would undermine the point rather than support it.
- **`agent/workflow.py` + `agent/state_store.py`** turn the single-pass
  pipeline into a genuinely multi-day, stateful simulation. Every other
  entry point re-decides from "attempt zero" every run; this one persists
  each transaction's attempt count, terminal/resolved status, and
  promise-to-pay deadline in SQLite across simulated days, so the retry
  sequencer actually progresses through its steps and a promise's due date
  actually arrives and gets checked — proof that "bounded recovery
  workflow" means a process unfolding over time, not five if-branches
  evaluated once.
- **`tests/` + CI** — 32 pytest tests covering the stopping rules, the
  root-cause detector's true positives/negatives, the retry sequence's
  progression and exhaustion, the promise tracker's classification, the
  simulator's uplift arithmetic, and the workflow's state machine (every
  transaction ends resolved or terminal; cumulative recovery never
  decreases). `.github/workflows/tests.yml` runs the suite on every push.
- **`api.py`** exposes the same pipeline as a FastAPI service
  (`/decide` for one transaction, `/batch/demo` for a full run), so
  "callable from a real backend" isn't just a claim in a README — it's a
  running endpoint.

## Key design decisions

- **Logistic regression over a heavier model, deliberately.** The
  recoverability score needs to be explainable per-transaction in a
  finance-adjacent, compliance-sensitive domain — a linear model's
  coefficients give an honest, exact per-feature contribution; a black-box
  model would need a separate explainability layer (SHAP etc.) for the same
  guarantee, which is more machinery than a hackathon timeline affords for
  no gain in this case.
- **Bounded action set.** The policy can only ever emit one of five named
  actions. This is what makes "compliant escalation with stopping rules"
  possible to audit at all — an open-ended agent that free-forms its next
  step can't be checked against a fixed rulebook the way a bounded one can.
- **Root-cause check runs before scoring is trusted.** A transaction that
  looks "recoverable" by the classifier but is actually failing because of
  a live infrastructure outage should not be retried or messaged — it
  should be left alone until the outage clears. Ordering this check ahead
  of the score-driven branch is what prevents wasted, annoying retries
  during a real degradation.
- **LLM and TTS are both optional, with graceful fallbacks.** A live demo
  or a judge's environment without an API key or an audio backend should
  still show the full pipeline working end-to-end.
