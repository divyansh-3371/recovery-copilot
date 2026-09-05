"""
Tracks how many times a real customer (identified by phone/email, since
that's all a real Razorpay webhook payload gives us) has had a payment
fail before -- this is exactly what a real merchant's own CRM/customer
database would supply, and its absence is what made agent/policy.py's
previous_attempts-gated routing (the voice_hinglish channel, for one)
structurally unreachable for every real transaction, regardless of what
actually happened: each real test payment creates a brand-new,
independent Razorpay order with no retry count of its own.

Deliberately separate from agent/state_store.py, which persists the
*synthetic* batch simulation's per-transaction state across simulated
days -- this tracks real customers across real, independent transactions,
a different concern with a different key (a person, not a transaction).
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = "data/live_customer_history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_failure_count (
    customer_key TEXT PRIMARY KEY,
    failure_count INTEGER NOT NULL DEFAULT 0
);
"""


@contextmanager
def _connect(db_path: str):
    dirname = os.path.dirname(db_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def customer_key(contact: str | None, email: str | None) -> str:
    """A stable identifier for a real customer across separate real
    transactions -- prefers phone (contact), the more stable of the two
    identifiers a Razorpay webhook gives us, falling back to email."""
    key = (contact or email or "").strip().lower()
    return key or "unknown"


def record_failure_and_get_count(contact: str | None, email: str | None, db_path: str = DB_PATH) -> int:
    """Records one more real payment failure for this customer and
    returns their new total count -- this becomes agent/policy.py's
    previous_attempts for a real webhook-driven transaction, in place of
    the hardcoded 0 that made attempt-count-gated routing structurally
    unreachable no matter what a real customer actually did."""
    key = customer_key(contact, email)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO customer_failure_count (customer_key, failure_count) VALUES (?, 1) "
            "ON CONFLICT(customer_key) DO UPDATE SET failure_count = failure_count + 1",
            (key,),
        )
        row = conn.execute(
            "SELECT failure_count FROM customer_failure_count WHERE customer_key = ?", (key,)
        ).fetchone()
        return row[0] if row else 1
