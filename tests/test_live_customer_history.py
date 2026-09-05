"""Tests for agent/live_customer_history.py -- the real per-customer
attempt tracking that replaces the previously-hardcoded previous_attempts=0
for real webhook-driven transactions."""
from agent import live_customer_history


def test_customer_key_prefers_contact(tmp_path):
    assert live_customer_history.customer_key("+919876543210", "a@b.com") == "+919876543210"


def test_customer_key_falls_back_to_email(tmp_path):
    assert live_customer_history.customer_key(None, "A@B.com") == "a@b.com"


def test_customer_key_unknown_when_both_missing(tmp_path):
    assert live_customer_history.customer_key(None, None) == "unknown"


def test_record_failure_increments_per_customer(tmp_path):
    db = str(tmp_path / "history.db")
    assert live_customer_history.record_failure_and_get_count("+911", "x@y.com", db_path=db) == 1
    assert live_customer_history.record_failure_and_get_count("+911", "x@y.com", db_path=db) == 2
    assert live_customer_history.record_failure_and_get_count("+911", "x@y.com", db_path=db) == 3


def test_record_failure_tracks_customers_independently(tmp_path):
    db = str(tmp_path / "history.db")
    assert live_customer_history.record_failure_and_get_count("+911", None, db_path=db) == 1
    assert live_customer_history.record_failure_and_get_count("+922", None, db_path=db) == 1
    assert live_customer_history.record_failure_and_get_count("+911", None, db_path=db) == 2


def test_record_failure_persists_across_connections(tmp_path):
    db = str(tmp_path / "history.db")
    live_customer_history.record_failure_and_get_count("+911", None, db_path=db)
    live_customer_history.record_failure_and_get_count("+911", None, db_path=db)
    # A fresh call (simulating a new request/process) sees the persisted count.
    assert live_customer_history.record_failure_and_get_count("+911", None, db_path=db) == 3
