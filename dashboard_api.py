"""
Read-oriented API surface for the React dashboard (frontend/). Mounted into
api.py's FastAPI app via an APIRouter -- one server, one port, same
security posture (rate limiting from api.py's middleware applies here too).

Reuses the exact same agent functions the project's CLIs use --
run_pipeline, run_workflow, decide, model.explain, build_call,
generate_message, estimate_cost -- so behavior is identical to what's
already tested, not a second implementation that could drift from it.
"""
from __future__ import annotations

import math
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from agent.audit import AuditTrail
from agent.classifier import RecoverabilityModel
from agent.cost_model import estimate_cost
from agent.messenger import generate_message
from agent.pipeline import run_pipeline
from agent.policy import decide
from agent.razorpay_client import build_call
from agent.workflow import run_workflow
from data.generate_data import CUSTOMER_SEGMENTS, FAILURE_REASONS, PAYMENT_METHODS, RISK_TYPES, generate

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

ACTION_LABEL = {
    "SEND_MESSAGE": "Sent a reminder",
    "RETRY_PAYMENT": "Retried the payment",
    "ESCALATE_HUMAN": "Sent to a specialist",
    "ESCALATE_COLLECTIONS": "Sent to collections/legal",
    "ESCALATE_OPS": "Flagged as a system issue",
    "STOP": "Left alone (not worth pursuing)",
}
RISK_TYPE_LABEL = {
    "payment_failure": "Payment failure",
    "checkout_abandonment": "Checkout drop-off",
    "subscription_failure": "Subscription failure",
    "invoice_overdue": "Overdue invoice",
}

# --- in-memory cache of (df, results, summary, systemic_issues) per seed --
# avoids re-running the whole pipeline on every request for the same seed.
_run_cache: dict[int, tuple] = {}
_timeline_cache: dict[tuple[int, int], "pd.DataFrame"] = {}


def _clean(value):
    """Recursively replaces NaN/Inf (not valid JSON) with None, and casts
    numpy/pandas scalars to plain Python types."""
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "item"):  # numpy scalar
        return _clean(value.item())
    return value


def _get_run(seed: int, model: RecoverabilityModel):
    if seed not in _run_cache:
        df = generate(seed=seed)
        results, summary, _, systemic_issues = run_pipeline(df, model=model)
        _run_cache[seed] = (df, results, summary, systemic_issues)
    return _run_cache[seed]


@router.get("/options")
def options() -> dict:
    return {
        "risk_types": RISK_TYPES,
        "failure_reasons": FAILURE_REASONS,
        "payment_methods": PAYMENT_METHODS,
        "customer_segments": CUSTOMER_SEGMENTS,
        "action_labels": ACTION_LABEL,
        "risk_type_labels": RISK_TYPE_LABEL,
    }


@router.get("/summary")
def summary(seed: int = Query(default=42, ge=1, le=9999)) -> dict:
    from api import get_model  # local import avoids a circular import at module load time
    df, results, summary_dict, systemic_issues = _get_run(seed, get_model())

    category = (
        results.groupby("risk_type")[["baseline_recovered_amount", "agent_recovered_amount"]]
        .sum().reset_index().to_dict(orient="records")
    )
    action_counts = results["agent_action"].value_counts()
    action_breakdown = []
    for action, count in action_counts.items():
        example = results[results["agent_action"] == action].iloc[0]
        action_breakdown.append({
            "action": action, "count": int(count),
            "example_transaction_id": example["transaction_id"],
        })
    top_reasons = (
        results.groupby("failure_reason")["amount"].sum().sort_values(ascending=False).head(5).reset_index()
        .to_dict(orient="records")
    )
    in_progress = int((results["agent_action"] != "STOP").sum()) - int(results["agent_resolved"].sum())

    return _clean({
        "summary": summary_dict,
        "systemic_issues": [issue.__dict__ | {"note": issue.note} for issue in systemic_issues.values()],
        "category_breakdown": category,
        "action_breakdown": action_breakdown,
        "top_reasons": top_reasons,
        "in_progress": in_progress,
        "n_transactions": len(df),
    })


@router.get("/transactions")
def transactions(
    seed: int = Query(default=42, ge=1, le=9999),
    risk_type: str | None = None,
    action: str | None = None,
    customer_segment: str | None = None,
) -> dict:
    from api import get_model
    df, results, _, _ = _get_run(seed, get_model())

    view = results.copy()
    if risk_type:
        view = view[view["risk_type"] == risk_type]
    if action:
        view = view[view["agent_action"] == action]
    if customer_segment:
        view = view[view["customer_segment"] == customer_segment]

    view = view.sort_values("recoverability_score", ascending=False)
    rows = view[[
        "transaction_id", "risk_type", "failure_reason", "amount", "customer_segment",
        "recoverability_score", "agent_action", "agent_resolved", "agent_recovered_amount",
        "agent_intervention_cost",
    ]].rename(columns={"agent_intervention_cost": "intervention_cost"}).to_dict(orient="records")
    return _clean({"transactions": rows, "count": len(rows)})


@router.get("/transaction/{txn_id}")
def transaction_detail(txn_id: str, seed: int = Query(default=42, ge=1, le=9999)) -> dict:
    from api import get_model
    model = get_model()
    df, results, _, systemic_issues = _get_run(seed, model)

    match = df[df["transaction_id"] == txn_id]
    if match.empty:
        raise HTTPException(status_code=404, detail="Transaction not found in this seed's batch")
    row = match.iloc[0]
    res_row = results[results["transaction_id"] == txn_id].iloc[0]
    decision = decide(row, float(res_row["recoverability_score"]), systemic_issues)

    message = generate_message(row, decision) if decision.action == "SEND_MESSAGE" else None
    call = build_call(row, decision)
    audit = AuditTrail()
    trail = audit.for_transaction(txn_id)
    trail_records = (
        trail[["timestamp", "action", "reasoning", "stopping_rule_triggered", "systemic_issue_note"]]
        .to_dict(orient="records") if not trail.empty else []
    )

    return _clean({
        "transaction_id": txn_id,
        "customer_name": row["customer_name"],
        "customer_segment": row["customer_segment"],
        "amount": row["amount"],
        "risk_type": row["risk_type"],
        "failure_reason": row["failure_reason"],
        "payment_method": row["payment_method"],
        "score": float(res_row["recoverability_score"]),
        "explanation": [{"feature": f, "contribution": c} for f, c in model.explain(row, top_k=3)],
        "full_explanation": [{"feature": f, "contribution": c} for f, c in model.explain(row)],
        "decision": {
            "action": decision.action, "channel": decision.channel,
            "reasoning": decision.reasoning, "cost": float(res_row["agent_intervention_cost"]),
        },
        "promise_to_pay": {
            "status": res_row["promise_to_pay_status"], "note": res_row["promise_to_pay_note"],
        } if res_row["promise_to_pay_status"] in ("kept", "broken") else None,
        "message": message,
        "razorpay_call": {
            "method": call.method, "path": call.path, "payload": call.payload, "note": call.note,
        } if call else None,
        "audit_trail": trail_records,
    })


@router.get("/timeline")
def timeline(seed: int = Query(default=42, ge=1, le=9999), days: int = Query(default=5, ge=2, le=10)) -> dict:
    # run_workflow is genuinely slow (a real multi-day SQLite-backed
    # simulation, ~10s+) -- cached per (seed, days) so repeat requests
    # (a tab revisit, a page reload) don't re-pay that cost, matching the
    # cheap/instant feel of every other dashboard endpoint.
    cache_key = (seed, days)
    if cache_key not in _timeline_cache:
        from api import get_model
        df = generate(seed=seed)
        model = get_model()
        daily = run_workflow(
            df, model, n_days=days,
            db_path=f"data/workflow_state_{seed}.db",
            audit_path=f"data/workflow_audit_log_{seed}.jsonl",
        )
        _timeline_cache[cache_key] = daily
    return _clean({"days": _timeline_cache[cache_key].to_dict(orient="records")})


class TryTransactionIn(BaseModel):
    risk_type: str
    failure_reason: str
    amount: float = Field(gt=0, le=10_000_000)
    payment_method: str
    customer_segment: str
    previous_attempts: int = Field(default=0, ge=0, le=20)
    customer_local_hour: int = Field(default=12, ge=0, le=23)
    do_not_contact: bool = False

    @model_validator(mode="after")
    def _check(self) -> "TryTransactionIn":
        if self.risk_type not in RISK_TYPES:
            raise ValueError(f"risk_type must be one of {RISK_TYPES}")
        if self.failure_reason not in FAILURE_REASONS.get(self.risk_type, []):
            raise ValueError(f"failure_reason invalid for risk_type {self.risk_type!r}")
        if self.payment_method not in PAYMENT_METHODS:
            raise ValueError(f"payment_method must be one of {PAYMENT_METHODS}")
        if self.customer_segment not in CUSTOMER_SEGMENTS:
            raise ValueError(f"customer_segment must be one of {CUSTOMER_SEGMENTS}")
        return self


@router.post("/try")
def try_transaction(body: TryTransactionIn) -> dict:
    from api import get_model
    model = get_model()
    row = pd.Series({
        "transaction_id": "live_test_0001",
        "customer_name": "Test Customer",
        "amount": float(body.amount),
        "currency": "INR",
        "risk_type": body.risk_type,
        "failure_reason": body.failure_reason,
        "payment_method": body.payment_method,
        "customer_segment": body.customer_segment,
        "previous_attempts": int(body.previous_attempts),
        "do_not_contact": bool(body.do_not_contact),
        "customer_local_hour": int(body.customer_local_hour),
        "days_since_event": 0,
        "_true_recoverable_prob": 0.0,
    })
    score = float(model.predict_proba(pd.DataFrame([row]))[0])
    decision = decide(row, score, {})
    message = generate_message(row, decision) if decision.action == "SEND_MESSAGE" else None
    call = build_call(row, decision)

    return _clean({
        "score": score,
        "explanation": [{"feature": f, "contribution": c} for f, c in model.explain(row, top_k=3)],
        "full_explanation": [{"feature": f, "contribution": c} for f, c in model.explain(row)],
        "decision": {
            "action": decision.action, "channel": decision.channel,
            "reasoning": decision.reasoning, "cost": estimate_cost(decision),
            "retry_method": decision.retry_method, "retry_delay_hours": decision.retry_delay_hours,
        },
        "message": message,
        "razorpay_call": {
            "method": call.method, "path": call.path, "payload": call.payload, "note": call.note,
        } if call else None,
    })


@router.get("/live-transactions")
def live_transactions() -> dict:
    audit = AuditTrail(path="data/live_audit_log.jsonl")
    df = audit.load_all()
    if df.empty:
        return {"transactions": []}
    df = df.sort_values("timestamp", ascending=False)
    cols = [c for c in [
        "transaction_id", "timestamp", "action", "reasoning", "failure_reason", "amount",
        "customer_segment", "recoverability_score", "event", "raw_error_reason",
        "raw_error_code", "raw_error_description", "executed", "execution_detail",
        "intervention_cost", "retry_of_transaction_id",
    ] if c in df.columns]
    return _clean({"transactions": df[cols].to_dict(orient="records")})
