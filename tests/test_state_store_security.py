"""Tests that update_state refuses to write to any column outside its
allowlist -- this is what actually stops a SQL-injection-via-column-name
attempt, since SQLite can't parameterize identifiers, only values."""
import pandas as pd
import pytest

from agent.state_store import connect, init_states, update_state


def test_update_state_rejects_unknown_column(tmp_path):
    db_path = str(tmp_path / "state.db")
    df = pd.DataFrame([{"transaction_id": "txn_1", "previous_attempts": 0}])
    with connect(db_path) as conn:
        init_states(conn, df)
        with pytest.raises(ValueError):
            update_state(conn, "txn_1", **{"transaction_id = '' OR '1'='1'; --": "x"})


def test_update_state_rejects_primary_key_overwrite_attempt(tmp_path):
    """transaction_id is a named parameter of update_state itself, not a
    **fields entry -- so it can never be smuggled into the SET clause via
    an attacker-controlled fields dict; Python's own call binding rejects
    the attempt before the allowlist check even runs."""
    db_path = str(tmp_path / "state.db")
    df = pd.DataFrame([{"transaction_id": "txn_1", "previous_attempts": 0}])
    attacker_controlled_fields = {"transaction_id": "txn_hijacked"}
    with connect(db_path) as conn:
        init_states(conn, df)
        with pytest.raises(TypeError):
            update_state(conn, "txn_1", **attacker_controlled_fields)


def test_update_state_accepts_known_columns(tmp_path):
    db_path = str(tmp_path / "state.db")
    df = pd.DataFrame([{"transaction_id": "txn_1", "previous_attempts": 0}])
    with connect(db_path) as conn:
        init_states(conn, df)
        update_state(conn, "txn_1", resolved=1, recovered_amount=500.0)
        cur = conn.execute(
            "SELECT resolved, recovered_amount FROM transaction_state WHERE transaction_id = ?", ("txn_1",)
        )
        row = cur.fetchone()
        assert row["resolved"] == 1
        assert row["recovered_amount"] == 500.0


def test_update_state_with_no_fields_is_a_noop(tmp_path):
    db_path = str(tmp_path / "state.db")
    df = pd.DataFrame([{"transaction_id": "txn_1", "previous_attempts": 0}])
    with connect(db_path) as conn:
        init_states(conn, df)
        update_state(conn, "txn_1")  # should not raise, should not touch anything
