"""
Portfolio-level root-cause / payment-degradation detector.

Individual failed transactions are usually treated as isolated customer
problems ("card declined, nudge the customer"). But a chunk of failures are
actually *infrastructure* degradation -- a bank's netbanking gateway timing
out, a specific issuer's mandate pipeline erroring -- and retrying or
messaging the customer for those is both useless and a bad experience.

This module looks across the whole batch for (payment_method, failure_reason)
combinations whose *recent* rate is elevated well above their own recent
baseline, and flags them as likely systemic issues rather than customer-side
failures. The policy engine consults these flags before deciding to retry.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

INFRA_FAILURE_REASONS = {"bank_timeout", "network_drop", "mandate_bank_error", "issuer_declined"}

RECENT_DAYS_WINDOW = 1
MIN_RECENT_COUNT = 5
RATIO_THRESHOLD = 1.6


@dataclass(frozen=True)
class SystemicIssue:
    payment_method: str
    failure_reason: str
    recent_count: int
    recent_rate_per_day: float
    baseline_rate_per_day: float
    ratio: float

    @property
    def note(self) -> str:
        return (
            f"{self.payment_method.upper()} '{self.failure_reason}' failures are running "
            f"{self.ratio:.1f}x above baseline ({self.recent_count} in the last "
            f"{RECENT_DAYS_WINDOW}d) — likely an infra/bank-side degradation, not a "
            f"customer-side problem. Pausing customer-facing retries; escalating to ops."
        )


def detect_systemic_issues(
    df: pd.DataFrame,
    recent_days: int = RECENT_DAYS_WINDOW,
    min_recent_count: int = MIN_RECENT_COUNT,
    ratio_threshold: float = RATIO_THRESHOLD,
) -> dict[tuple[str, str], SystemicIssue]:
    subset = df[df["failure_reason"].isin(INFRA_FAILURE_REASONS)]
    if subset.empty:
        return {}

    max_age = int(subset["days_since_event"].max())
    older_span = max(max_age - recent_days, 1)

    flags: dict[tuple[str, str], SystemicIssue] = {}
    for (method, reason), group in subset.groupby(["payment_method", "failure_reason"]):
        recent = group[group["days_since_event"] <= recent_days]
        older = group[group["days_since_event"] > recent_days]

        recent_rate = len(recent) / recent_days
        baseline_rate = len(older) / older_span if not older.empty else 0.5
        baseline_rate = max(baseline_rate, 0.5)  # floor to avoid div-by-near-zero explosions
        ratio = recent_rate / baseline_rate

        if len(recent) >= min_recent_count and ratio >= ratio_threshold:
            flags[(method, reason)] = SystemicIssue(
                payment_method=method,
                failure_reason=reason,
                recent_count=len(recent),
                recent_rate_per_day=recent_rate,
                baseline_rate_per_day=baseline_rate,
                ratio=ratio,
            )
    return flags
