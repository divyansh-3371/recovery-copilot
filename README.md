# Recovery Copilot

**Track:** AI Revenue Recovery — Razorpay AI Buildathon 2026

An agent that detects revenue at risk (failed payments, checkout abandonment,
subscription/mandate failures, overdue B2B invoices), decides the right
*bounded* intervention, and executes it — with measured recovered ₹, a
compliant stopping-rules policy, and a complete audit trail.

## The Bar this project targets

| Requirement | Where it's satisfied |
|---|---|
| Demonstrate measured money recovered from a batch of transactions | `agent/simulator.py` runs the agent's decisions *and* a naive baseline over the same batch and reports the real ₹ delta — see the dashboard's KPI row |
| Compliant escalation procedures with stopping rules | `agent/policy.py` — do-not-contact, max-attempt cap, uneconomical-amount floor, quiet-hours deferral, all checked before any customer-facing action |
| Complete audit trail for all actions | `agent/audit.py` — one JSON line per decision, with full reasoning, written to `data/audit_log.jsonl` |
| Move beyond detection to actual recovery execution | The policy engine doesn't just flag risk — it picks a concrete action (`RETRY_PAYMENT`, `SEND_MESSAGE`, `ESCALATE_HUMAN`, `ESCALATE_OPS`, `STOP`) and the simulator resolves its real outcome |

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
                    app.py (Streamlit dashboard)
```

See `pitch/architecture.md` for the fuller write-up.

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
- **`tests/` (32 tests) + `.github/workflows/tests.yml`** — the stopping
  rules, the root-cause detector, the retry sequencer, the promise tracker,
  the simulator's uplift math, and the workflow's state machine all have
  tests; CI runs them on every push.
- **`api.py`** — the same pipeline exposed as a FastAPI service
  (`/decide`, `/batch/demo`), so it's callable from a real backend, not only
  runnable as a CLI or a Streamlit demo.

## Tech stack

Pure Python: `pandas` / `numpy` for data, `scikit-learn` for the recoverability
model, `Streamlit` + `Plotly` for the dashboard, `anthropic` (optional, with a
graceful template fallback) for message generation, `pyttsx3` for fully
offline text-to-speech on the Hinglish voice channel, `sqlite3` (stdlib) for
workflow state, `pytest` for tests, `fastapi`/`uvicorn` for the service layer.

## Running it

```bash
pip install -r requirements.txt

# CLI: runs the full pipeline on a fresh synthetic batch, prints the summary
python run_batch.py

# Multi-day stateful workflow simulation
python simulate_workflow.py --days 5

# Test suite
pytest -q

# Dashboard
streamlit run app.py

# API service
uvicorn api:app --reload
```

Optional: set `ANTHROPIC_API_KEY` in your environment for LLM-generated
recovery messages; without it, the messenger falls back to a clean
deterministic template so the demo never breaks.

## What's real vs. simulated

This is a buildathon MVP, built honestly:
- **Real:** the trained classifier, the decision/policy engine, the stopping
  rules, the audit trail, the root-cause anomaly detector, the LLM message
  generation, the offline TTS, the multi-day state machine, the test suite,
  the API service.
- **Simulated:** the transaction data itself and whether an intervention
  "succeeds" — both come from `data/generate_data.py`, which encodes a hidden
  ground-truth recoverability prior never seen by the agent, used only by
  `agent/simulator.py` (and `agent/workflow.py`, day by day) to resolve
  realistic outcomes. In production this batch would be a merchant's real
  failed-transaction feed and the training data would be their real
  resolved-case history; the Razorpay API calls in `agent/razorpay_client.py`
  are stubs illustrating integration shape, not live calls.

## Project structure

```
data/generate_data.py     synthetic batch generator (+ injected outage)
agent/features.py         shared feature engineering
agent/classifier.py       recoverability model (train + explain)
agent/root_cause.py       portfolio-level degradation detector
agent/retry_sequencer.py  explicit mandate/payment retry sequence
agent/promise_tracker.py  promise-to-pay classification
agent/policy.py           decision engine + stopping rules
agent/messenger.py        message generation (LLM + template) + offline TTS
agent/razorpay_client.py  action -> Razorpay API call stub mapping
agent/audit.py            append-only audit trail
agent/simulator.py        outcome simulation + baseline comparison
agent/state_store.py      SQLite persistence for the multi-day workflow
agent/workflow.py         multi-day stateful workflow orchestrator
agent/pipeline.py         single-pass orchestrator
run_batch.py              CLI: single-pass batch run
simulate_workflow.py      CLI: multi-day workflow simulation
app.py                    Streamlit dashboard
api.py                    FastAPI service (/decide, /batch/demo)
tests/                    pytest suite (32 tests)
.github/workflows/        CI: runs the test suite on every push
pitch/                    architecture doc, pitch script, build-challenges log
```

## Build challenges & how they were resolved

See `pitch/build_challenges.md` for the full log — this is also the source
for the submission form's "Build Challenges & Technical Obstacles" field.
