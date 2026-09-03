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
