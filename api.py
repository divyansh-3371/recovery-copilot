"""
Thin FastAPI service exposing the same agent pipeline used by the CLI and
the Streamlit dashboard, so Recovery Copilot can be called as a service
from a real backend instead of only ever run as a demo.

Run with:
    uvicorn api:app --reload

Then, for example:
    curl -X POST http://localhost:8000/batch/demo?n=100
    curl http://localhost:8000/health
"""
from __future__ import annotations

import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

from agent.classifier import RecoverabilityModel, train_default_model
from agent.pipeline import run_pipeline
from agent.policy import decide as policy_decide
from agent.razorpay_client import build_call
from data.generate_data import generate

app = FastAPI(
    title="Recovery Copilot API",
    description="AI Revenue Recovery agent -- score, decide, and (in production) execute "
                "bounded recovery actions on at-risk revenue.",
    version="0.1.0",
)

_model: RecoverabilityModel | None = None


def get_model() -> RecoverabilityModel:
    global _model
    if _model is None:
        _model = train_default_model()
    return _model


class TransactionIn(BaseModel):
    transaction_id: str
    customer_id: str = "cust_unknown"
    customer_name: str = ""
    amount: float
    currency: str = "INR"
    risk_type: str
    failure_reason: str
    payment_method: str
    customer_segment: str = "returning"
    previous_attempts: int = 0
    do_not_contact: bool = False
    customer_local_hour: int = 12
    days_since_event: int = 0


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/batch/demo")
def batch_demo(n: int = 50, seed: int = 42) -> dict:
    """Runs the full pipeline on a fresh synthetic batch -- lets you smoke-test
    the service without wiring up a real transaction feed yet."""
    df = generate(n=n, seed=seed)
    results, summary, _, systemic_issues = run_pipeline(df, model=get_model())
    return {
        "summary": summary,
        "systemic_issues": [issue.note for issue in systemic_issues.values()],
        "action_breakdown": results["agent_action"].value_counts().to_dict(),
    }


@app.post("/decide")
def decide_one(txn: TransactionIn) -> dict:
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
