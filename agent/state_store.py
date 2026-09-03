"""
Lightweight persistence for the multi-day workflow simulation. SQLite so
there's no extra dependency -- each transaction's recovery state (attempts
so far, whether it's resolved, promise-to-pay status) persists across
simulated days, instead of every pipeline run being a stateless one-shot
decision on a fresh batch.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = "data/workflow_state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transaction_state (
    transaction_id TEXT PRIMARY KEY,
    previous_attempts INTEGER NOT NULL DEFAULT 0,
    resolved INTEGER NOT NULL DEFAULT 0,
    recovered_amount REAL NOT NULL DEFAULT 0,
    terminal INTEGER NOT NULL DEFAULT 0,
    terminal_reason TEXT,
    promise_status TEXT,
    promise_due_day INTEGER,
    last_action TEXT,
    last_updated_day INTEGER NOT NULL DEFAULT 0
);
"""


def reset(db_path: str = DB_PATH) -> None:
    if os.path.exists(db_path):
        os.remove(db_path)


@contextmanager
def connect(db_path: str = DB_PATH):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_states(conn: sqlite3.Connection, df) -> None:
    for _, row in df.iterrows():
        conn.execute(
            "INSERT OR IGNORE INTO transaction_state (transaction_id, previous_attempts) VALUES (?, ?)",
            (row["transaction_id"], int(row["previous_attempts"])),
        )


def get_state(conn: sqlite3.Connection, transaction_id: str) -> sqlite3.Row:
    cur = conn.execute("SELECT * FROM transaction_state WHERE transaction_id = ?", (transaction_id,))
    return cur.fetchone()


def update_state(conn: sqlite3.Connection, transaction_id: str, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [transaction_id]
    conn.execute(f"UPDATE transaction_state SET {sets} WHERE transaction_id = ?", values)
