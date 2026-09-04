"""Tests for the audit trail, including the real bug this was written to
fix: a torn/partial line from a concurrent writer must not crash the whole
read (see build_challenges.md #14) -- it must be skipped, not fatal."""
from agent.audit import AuditTrail


def test_missing_file_returns_empty_dataframe(tmp_path):
    audit = AuditTrail(path=str(tmp_path / "does_not_exist.jsonl"))
    df = audit.load_all()
    assert df.empty


def test_log_then_load_round_trips(tmp_path):
    audit = AuditTrail(path=str(tmp_path / "audit.jsonl"))
    audit.reset()
    audit.log(transaction_id="txn_1", action="SEND_MESSAGE", reasoning=["because reasons"])
    audit.log(transaction_id="txn_2", action="STOP", reasoning=["nope"])

    df = audit.load_all()
    assert len(df) == 2
    assert set(df["transaction_id"]) == {"txn_1", "txn_2"}


def test_for_transaction_filters_correctly(tmp_path):
    audit = AuditTrail(path=str(tmp_path / "audit.jsonl"))
    audit.reset()
    audit.log(transaction_id="txn_1", action="SEND_MESSAGE", reasoning=["a"])
    audit.log(transaction_id="txn_2", action="STOP", reasoning=["b"])
    audit.log(transaction_id="txn_1", action="RETRY_PAYMENT", reasoning=["c"])

    trail = audit.for_transaction("txn_1")
    assert len(trail) == 2
    assert set(trail["action"]) == {"SEND_MESSAGE", "RETRY_PAYMENT"}


def test_torn_line_is_skipped_not_fatal(tmp_path):
    """The actual failure mode: a concurrent writer's reset() truncates the
    file mid-write from another process, splitting one JSON entry across
    two garbled lines. load_all() must skip those, not raise."""
    path = tmp_path / "audit.jsonl"
    path.write_text(
        '{"trace_id": "a", "transaction_id": "txn_1", "action": "STOP"}\n'
        'hours": 2.0, "scheduled_hour": null}\n'          # torn line, no leading brace
        '{"trace_id": "b", "transaction_id": "txn_2", "action": "SEND_MESSAGE"}\n'
        '0.0}\n'                                            # torn line, trailing fragment only
        '\n'                                                # a blank line
        '{"trace_id": "c", "transaction_id": "txn_3", "action": "RETRY_PAYMENT"}\n',
        encoding="utf-8",
    )
    audit = AuditTrail(path=str(path))
    df = audit.load_all()  # must not raise
    assert len(df) == 3
    assert set(df["transaction_id"]) == {"txn_1", "txn_2", "txn_3"}


def test_reset_clears_previous_entries(tmp_path):
    audit = AuditTrail(path=str(tmp_path / "audit.jsonl"))
    audit.log(transaction_id="txn_1", action="STOP", reasoning=["a"])
    audit.reset()
    audit.log(transaction_id="txn_2", action="STOP", reasoning=["b"])

    df = audit.load_all()
    assert list(df["transaction_id"]) == ["txn_2"]
