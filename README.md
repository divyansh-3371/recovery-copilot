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

## Tech stack

Pure Python: `pandas` / `numpy` for data, `scikit-learn` for the recoverability
model, `Streamlit` + `Plotly` for the dashboard, `anthropic` (optional, with a
graceful template fallback) for message generation, `pyttsx3` for fully
offline text-to-speech on the Hinglish voice channel.

## Running it

```bash
pip install -r requirements.txt

# CLI: runs the full pipeline on a fresh synthetic batch, prints the summary
python run_batch.py

# Dashboard
streamlit run app.py
```

Optional: set `ANTHROPIC_API_KEY` in your environment for LLM-generated
recovery messages; without it, the messenger falls back to a clean
deterministic template so the demo never breaks.

## What's real vs. simulated

This is a buildathon MVP, built honestly:
- **Real:** the trained classifier, the decision/policy engine, the stopping
  rules, the audit trail, the root-cause anomaly detector, the LLM message
  generation, the offline TTS.
- **Simulated:** the transaction data itself and whether an intervention
  "succeeds" — both come from `data/generate_data.py`, which encodes a hidden
  ground-truth recoverability prior never seen by the agent, used only by
  `agent/simulator.py` to resolve realistic outcomes. In production this
  batch would be a merchant's real failed-transaction feed and the training
  data would be their real resolved-case history.

## Project structure

```
data/generate_data.py   synthetic batch generator (+ injected outage)
agent/features.py       shared feature engineering
agent/classifier.py     recoverability model (train + explain)
agent/root_cause.py     portfolio-level degradation detector
agent/policy.py         decision engine + stopping rules
agent/messenger.py      message generation (LLM + template) + offline TTS
agent/audit.py          append-only audit trail
agent/simulator.py      outcome simulation + baseline comparison
agent/pipeline.py       orchestrates the above
run_batch.py            CLI entry point
app.py                  Streamlit dashboard
pitch/                  architecture doc, pitch script, build-challenges log
```

## Build challenges & how they were resolved

See `pitch/build_challenges.md` for the full log — this is also the source
for the submission form's "Build Challenges & Technical Obstacles" field.
