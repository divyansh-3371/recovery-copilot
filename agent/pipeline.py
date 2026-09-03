"""Orchestrates one end-to-end batch run of the Recovery Copilot agent:
classify -> detect systemic issues -> decide -> audit -> simulate outcome."""
from __future__ import annotations

import pandas as pd

from agent.audit import AuditTrail
from agent.classifier import RecoverabilityModel, train_default_model
from agent.policy import decide
from agent.root_cause import detect_systemic_issues
from agent.simulator import simulate_batch, summarize


def run_pipeline(
    df: pd.DataFrame,
    model: RecoverabilityModel | None = None,
    audit_path: str = "data/audit_log.jsonl",
) -> tuple[pd.DataFrame, dict, RecoverabilityModel, dict]:
    if model is None:
        model = train_default_model()

    scores = model.predict_proba(df)
    systemic_issues = detect_systemic_issues(df)

    audit = AuditTrail(path=audit_path)
    audit.reset()

    decisions = []
    for (_, row), score in zip(df.iterrows(), scores):
        decision = decide(row, float(score), systemic_issues)
        audit.log(
            transaction_id=decision.transaction_id,
            action=decision.action,
            reasoning=decision.reasoning,
            stopping_rule_triggered=decision.stopping_rule_triggered,
            systemic_issue_note=decision.systemic_issue_note,
            extra={
                "recoverability_score": decision.recoverability_score,
                "channel": decision.channel,
                "retry_delay_hours": decision.retry_delay_hours,
                "scheduled_hour": decision.scheduled_hour,
            },
        )
        decisions.append(decision)

    results = simulate_batch(df, decisions, systemic_issues)

    # promise-to-pay tracker: a broken promise gets its own audit entry and
    # an explicit escalation, rather than silently vanishing from the trail
    broken = results[results["promise_to_pay_status"] == "broken"]
    for _, r in broken.iterrows():
        audit.log(
            transaction_id=r["transaction_id"],
            action="ESCALATE_HUMAN",
            reasoning=[r["promise_to_pay_note"], "Promise-to-pay tracker: escalating broken promise for manual follow-up."],
            extra={"escalation_source": "promise_to_pay_tracker"},
        )

    summary = summarize(results)
    return results, summary, model, systemic_issues
