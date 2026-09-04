"""
Append-only audit trail. Every action the agent takes — including deciding to
do nothing — gets one JSON line here, with a full reasoning trace and a
timestamp. This is what lets a compliance reviewer (or a judge) reconstruct
exactly why the agent did what it did for any single transaction.

The default path is a single shared file, and it's written from more than
one process in normal use -- the live dashboard on its own writes here, and
so does every CLI run (run_batch.py, simulate_workflow.py) unless told
otherwise. If a reset() (which truncates the file) lands mid-read from
another process, the reader can observe a torn/partial line -- this is what
crashed the dashboard the first time it happened (see build_challenges.md
#14). load_all() is defensive about this: a line that fails to parse is
skipped, not fatal to the whole audit trail.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import pandas as pd

logger = logging.getLogger("recovery_copilot.audit")

DEFAULT_LOG_PATH = "data/audit_log.jsonl"


class AuditTrail:
    def __init__(self, path: str = DEFAULT_LOG_PATH):
        self.path = path

    def reset(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8"):
            pass

    def log(self, transaction_id: str, action: str, reasoning: list[str],
             stopping_rule_triggered: str | None = None,
             systemic_issue_note: str | None = None,
             extra: dict | None = None) -> None:
        entry = {
            "trace_id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": "recovery_copilot_agent",
            "action": action,
            "reasoning": reasoning,
            "stopping_rule_triggered": stopping_rule_triggered,
            "systemic_issue_note": systemic_issue_note,
        }
        if extra:
            entry.update(extra)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def load_all(self) -> pd.DataFrame:
        if not os.path.exists(self.path):
            return pd.DataFrame()
        rows = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return pd.DataFrame()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # a torn/partial line -- most likely another process's
                # reset() truncated this file mid-read (see the module
                # docstring). Skip it rather than let one bad line take
                # down the whole audit trail.
                logger.warning("Skipping unparseable audit log line in %s", self.path)
                continue
        return pd.DataFrame(rows)

    def for_transaction(self, transaction_id: str) -> pd.DataFrame:
        df = self.load_all()
        if df.empty:
            return df
        return df[df["transaction_id"] == transaction_id]
