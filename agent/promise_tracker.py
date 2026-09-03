"""
Promise-to-pay tracker.

When a customer is messaged about an overdue invoice or a failed
subscription, some respond by promising to pay by a specific date rather
than paying immediately. Treating that as the end of the story is how
"recovery" quietly turns back into unrecovered revenue — this module
records the promise and classifies whether it was kept, so a broken promise
triggers an explicit escalation instead of silently disappearing.

Deliberately reuses the batch's own resolved outcome (whether the money was
actually recovered) as the ground truth for "was the promise kept" — it
does not introduce a second independent coin flip, so the promise-to-pay
layer is a *classification* of what already happened, not a separate
simulation that could contradict the recovered-₹ numbers.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

PROMISE_ELIGIBLE_RISK_TYPES = {"invoice_overdue", "subscription_failure"}

BASE_PROMISE_LIKELIHOOD = {"invoice_overdue": 0.55, "subscription_failure": 0.40}
SEGMENT_ADJ = {"vip": +0.15, "returning": +0.05, "new": -0.05}


@dataclass(frozen=True)
class PromiseRecord:
    status: str  # "not_applicable" | "not_offered" | "kept" | "broken"
    promised_in_days: int | None = None

    @property
    def note(self) -> str | None:
        if self.status == "kept":
            return f"Customer promised to pay within {self.promised_in_days}d - promise kept."
        if self.status == "broken":
            return (f"Customer promised to pay within {self.promised_in_days}d - promise broken. "
                     f"Auto-escalating to a human recovery agent rather than letting it silently drop.")
        return None


def classify_promise(row: pd.Series, action: str, resolved: bool, rng: np.random.Generator) -> PromiseRecord:
    if action != "SEND_MESSAGE" or row["risk_type"] not in PROMISE_ELIGIBLE_RISK_TYPES:
        return PromiseRecord(status="not_applicable")

    likelihood = BASE_PROMISE_LIKELIHOOD[row["risk_type"]] + SEGMENT_ADJ[row["customer_segment"]]
    if rng.random() >= likelihood:
        return PromiseRecord(status="not_offered")

    promised_in_days = int(rng.integers(3, 15))
    return PromiseRecord(status="kept" if resolved else "broken", promised_in_days=promised_in_days)
