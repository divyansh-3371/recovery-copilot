"""Tests for the multi-day stateful workflow: every transaction must end up
either resolved or terminal, cumulative recovery must never decrease, and
running it must actually persist state across days (not reset each day)."""
from agent.classifier import RecoverabilityModel
from agent.workflow import run_workflow
from data.generate_data import generate


def _tiny_model() -> RecoverabilityModel:
    return RecoverabilityModel().fit(generate(n=200, seed=11))


def test_every_transaction_ends_resolved_or_terminal(tmp_path):
    df = generate(n=60, seed=5)
    model = _tiny_model()
    db_path = str(tmp_path / "state.db")
    audit_path = str(tmp_path / "audit.jsonl")

    run_workflow(df, model, n_days=5, db_path=db_path, audit_path=audit_path)

    from agent.state_store import connect
    with connect(db_path) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM transaction_state WHERE resolved = 0 AND terminal = 0")
        stuck = cur.fetchone()[0]
        cur2 = conn.execute("SELECT COUNT(*) FROM transaction_state")
        total = cur2.fetchone()[0]
    assert stuck == 0
    assert total == len(df)


def test_cumulative_recovery_is_monotonically_non_decreasing(tmp_path):
    df = generate(n=60, seed=6)
    model = _tiny_model()
    daily = run_workflow(df, model, n_days=5, db_path=str(tmp_path / "state.db"), audit_path=str(tmp_path / "audit.jsonl"))
    diffs = daily["cumulative_recovered"].diff().dropna()
    assert (diffs >= 0).all()


def test_independent_payment_still_counted_after_terminal_stop(tmp_path):
    """A do-not-contact transaction stops immediately (terminal on day 1),
    but must still be checked for -- and credited with -- an independent
    payment on a later day, not silently ignored forever just because the
    agent itself stopped acting on it."""
    import pandas as pd

    df = pd.DataFrame([{
        "transaction_id": "txn_dnc", "customer_id": "c1", "customer_name": "Test",
        "amount": 5000.0, "currency": "INR", "risk_type": "payment_failure",
        "failure_reason": "bank_timeout", "payment_method": "card",
        "customer_segment": "returning", "previous_attempts": 0,
        "do_not_contact": True, "customer_local_hour": 12, "days_since_event": 0,
        "_true_recoverable_prob": 0.95,
    }])
    model = _tiny_model()
    db_path = str(tmp_path / "state.db")
    audit_path = str(tmp_path / "audit.jsonl")

    run_workflow(df, model, n_days=40, db_path=db_path, audit_path=audit_path, seed=99)

    from agent.state_store import connect, get_state
    with connect(db_path) as conn:
        state = get_state(conn, "txn_dnc")
    assert state["terminal"] == 1
    assert state["terminal_reason"] == "do_not_contact"
    assert state["resolved"] == 1  # recovered independently despite being stopped

    from agent.audit import AuditTrail
    trail = AuditTrail(path=audit_path).load_all()
    cancels = trail[(trail["transaction_id"] == "txn_dnc") & (trail["action"] == "IDEMPOTENT_CANCEL")]
    assert len(cancels) == 1
    assert bool(cancels.iloc[0]["was_terminal"]) is True


def test_idempotent_cancellation_fires_and_is_audited(tmp_path):
    """Guardrail: a customer paying independently, through a channel the
    agent never touched, must be detected and logged -- not silently
    missed, and not left to keep getting retried/messaged afterward."""
    df = generate(n=150, seed=7)
    model = _tiny_model()
    db_path = str(tmp_path / "state.db")
    audit_path = str(tmp_path / "audit.jsonl")

    run_workflow(df, model, n_days=6, db_path=db_path, audit_path=audit_path)

    from agent.audit import AuditTrail
    trail = AuditTrail(path=audit_path).load_all()
    cancels = trail[trail["action"] == "IDEMPOTENT_CANCEL"]
    assert len(cancels) > 0  # with 150 transactions over 6 days, at least one should fire

    # once cancelled, that transaction must be resolved and never acted on again
    from agent.state_store import connect
    with connect(db_path) as conn:
        for txn_id in cancels["transaction_id"].unique():
            cur = conn.execute("SELECT resolved FROM transaction_state WHERE transaction_id = ?", (txn_id,))
            assert cur.fetchone()["resolved"] == 1
