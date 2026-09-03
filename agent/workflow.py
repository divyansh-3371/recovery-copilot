"""
Multi-day workflow simulation.

Every other entry point (run_batch.py, the dashboard's default view) makes
one stateless pass over a batch: score, decide, resolve, done. That proves
the decision logic works, but it doesn't prove "executes a bounded recovery
*workflow*" -- a workflow implies steps that unfold over time: a retry
sequence advancing from step 1 to step 2, a promise-to-pay deadline that
actually arrives and gets checked.

This module runs the same classifier/policy/simulator stack across N
simulated days, persisting each transaction's state (agent/state_store.py)
between days, so:
  - the mandate/payment retry sequencer genuinely progresses through its
    steps instead of always evaluating "attempt 0"
  - a promise-to-pay deadline set on day D is actually checked on day D,
    and a broken one is escalated then -- not resolved in the same breath
    it was made
  - a systemic issue detected on day 1 is assumed to clear after
    SYSTEMIC_ISSUE_CLEARS_AFTER_DAY days, so ESCALATE_OPS transactions
    come back into the normal flow rather than being stuck forever
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from agent.audit import AuditTrail
from agent.classifier import RecoverabilityModel
from agent.policy import decide
from agent.promise_tracker import classify_promise
from agent.root_cause import detect_systemic_issues
from agent.simulator import agent_outcome_multiplier
from agent.state_store import DB_PATH, connect, get_state, init_states, reset, update_state

SYSTEMIC_ISSUE_CLEARS_AFTER_DAY = 1
ATTEMPT_ACTIONS = {"RETRY_PAYMENT", "SEND_MESSAGE", "ESCALATE_HUMAN"}

# Idempotency / guardrail: a customer can pay through a channel the agent
# never touched -- their own banking app, a direct UPI payment, walking into
# a branch -- entirely independent of whatever this agent last scheduled.
# Without a check for this, the workflow would keep retrying/messaging/
# escalating someone who has already paid. This models that independent
# path and, when it fires, cancels every remaining scheduled action for
# that transaction with an explicit audit entry -- not just an implicit
# side effect of the "skip if resolved" loop guard below.
INDEPENDENT_PAY_BASE_PROB = 0.03
INDEPENDENT_PAY_SCORE_WEIGHT = 0.05


def run_workflow(
    df: pd.DataFrame,
    model: RecoverabilityModel,
    n_days: int = 5,
    db_path: str = DB_PATH,
    audit_path: str = "data/workflow_audit_log.jsonl",
    seed: int = 777,
) -> pd.DataFrame:
    reset(db_path)
    rng = np.random.default_rng(seed)
    audit = AuditTrail(path=audit_path)
    audit.reset()

    systemic_issues = detect_systemic_issues(df)
    by_id = df.set_index("transaction_id", drop=False)

    daily_rows = []
    with connect(db_path) as conn:
        init_states(conn, df)

        for day in range(1, n_days + 1):
            day_systemic_issues = systemic_issues if day <= SYSTEMIC_ISSUE_CLEARS_AFTER_DAY else {}
            day_recovered = 0.0
            day_new_resolutions = 0

            for txn_id in by_id.index:
                state = get_state(conn, txn_id)
                if state["terminal"] or state["resolved"]:
                    continue

                row = by_id.loc[txn_id].copy()
                row["previous_attempts"] = state["previous_attempts"]

                # --- idempotency check: did the customer already pay through
                # a channel this agent never touched, independent of whatever
                # was last scheduled for them? Checked BEFORE deciding today's
                # action -- an agent that decides first and checks reality
                # second is the one that keeps hounding someone who already paid.
                independent_pay_prob = INDEPENDENT_PAY_BASE_PROB + INDEPENDENT_PAY_SCORE_WEIGHT * row["_true_recoverable_prob"]
                if bool(rng.random() < independent_pay_prob):
                    update_state(conn, txn_id, resolved=1, recovered_amount=row["amount"],
                                 last_action="INDEPENDENT_PAYMENT_DETECTED", last_updated_day=day)
                    audit.log(
                        transaction_id=txn_id, action="IDEMPOTENT_CANCEL",
                        reasoning=["Customer paid independently through another channel -- "
                                   "cancelling all remaining scheduled recovery actions for this transaction."],
                        extra={"day": day, "failure_reason": row["failure_reason"]},
                    )
                    day_recovered += row["amount"]
                    day_new_resolutions += 1
                    continue

                score = float(model.predict_proba(pd.DataFrame([row]))[0])
                decision = decide(row, score, day_systemic_issues)

                audit.log(
                    transaction_id=txn_id, action=decision.action, reasoning=decision.reasoning,
                    stopping_rule_triggered=decision.stopping_rule_triggered,
                    systemic_issue_note=decision.systemic_issue_note,
                    extra={"day": day, "recoverability_score": score, "failure_reason": row["failure_reason"]},
                )

                if decision.stopping_rule_triggered is not None:
                    update_state(conn, txn_id, terminal=1, terminal_reason=decision.stopping_rule_triggered,
                                 last_action=decision.action, last_updated_day=day)
                    continue

                if decision.action == "ESCALATE_OPS":
                    # not a customer-facing attempt -- re-evaluated once the issue clears
                    update_state(conn, txn_id, last_action=decision.action, last_updated_day=day)
                    continue

                eff_p = float(np.clip(
                    row["_true_recoverable_prob"] * agent_outcome_multiplier(decision, row["failure_reason"]),
                    0.0, 0.97,
                ))
                resolved_today = bool(rng.random() < eff_p)
                new_attempts = state["previous_attempts"] + (1 if decision.action in ATTEMPT_ACTIONS else 0)

                promise_status = state["promise_status"]
                promise_due_day = state["promise_due_day"]
                if decision.action == "SEND_MESSAGE" and promise_status is None:
                    promise = classify_promise(row, decision.action, resolved_today, rng)
                    if promise.status in ("kept", "broken"):
                        promise_status = "pending"
                        promise_due_day = day + max(1, promise.promised_in_days or 5)

                update_fields = {
                    "previous_attempts": new_attempts, "last_action": decision.action, "last_updated_day": day,
                    "promise_status": promise_status, "promise_due_day": promise_due_day,
                }
                if resolved_today:
                    update_fields.update(resolved=1, recovered_amount=row["amount"])
                    day_recovered += row["amount"]
                    day_new_resolutions += 1
                update_state(conn, txn_id, **update_fields)

                # outcome logging: the decision above was logged before its
                # result was known -- this closes the loop with what actually
                # happened, so the audit trail covers outcome, not just intent.
                audit.log(
                    transaction_id=txn_id, action="OUTCOME_RESOLVED" if resolved_today else "OUTCOME_UNRESOLVED",
                    reasoning=[f"Day {day} outcome for action '{decision.action}': "
                               f"{'recovered' if resolved_today else 'not recovered'}."],
                    extra={
                        "day": day, "failure_reason": row["failure_reason"],
                        "resolved": resolved_today,
                        "recovered_amount": row["amount"] if resolved_today else 0.0,
                    },
                )

                # promise deadline arriving: check whether it was kept
                if promise_status == "pending" and promise_due_day is not None and day >= promise_due_day:
                    kept = bool(get_state(conn, txn_id)["resolved"])
                    update_state(conn, txn_id, promise_status="kept" if kept else "broken")
                    if not kept:
                        audit.log(
                            transaction_id=txn_id, action="ESCALATE_HUMAN",
                            reasoning=[f"Promise-to-pay due on day {promise_due_day} was broken - escalating for manual follow-up."],
                            extra={"day": day, "escalation_source": "promise_to_pay_tracker"},
                        )

            cur = conn.execute("SELECT COUNT(*), COALESCE(SUM(recovered_amount), 0) FROM transaction_state WHERE resolved = 1")
            n_resolved, cumulative_recovered = cur.fetchone()
            daily_rows.append({
                "day": day,
                "resolved_today": day_new_resolutions,
                "recovered_today": day_recovered,
                "cumulative_resolved": n_resolved,
                "cumulative_recovered": cumulative_recovered,
            })

    return pd.DataFrame(daily_rows)
