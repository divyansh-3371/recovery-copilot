"""Tests for the portfolio-level root-cause / payment-degradation detector."""
import pandas as pd

from agent.root_cause import detect_systemic_issues


def _make_batch(n_recent: int, n_older: int, reason: str = "bank_timeout", method: str = "netbanking") -> pd.DataFrame:
    rows = []
    for i in range(n_recent):
        rows.append({"payment_method": method, "failure_reason": reason, "days_since_event": 0})
    for i in range(n_older):
        rows.append({"payment_method": method, "failure_reason": reason, "days_since_event": 5})
    return pd.DataFrame(rows)


def test_no_issue_on_flat_rate():
    df = _make_batch(n_recent=2, n_older=8)  # roughly flat rate, well under the count threshold
    issues = detect_systemic_issues(df)
    assert issues == {}


def test_detects_a_clear_spike():
    df = _make_batch(n_recent=25, n_older=5)
    issues = detect_systemic_issues(df, recent_days=1, min_recent_count=5, ratio_threshold=1.6)
    assert ("netbanking", "bank_timeout") in issues
    issue = issues[("netbanking", "bank_timeout")]
    assert issue.ratio > 1.6
    assert issue.recent_count == 25


def test_ignores_non_infra_failure_reasons():
    df = _make_batch(n_recent=25, n_older=1, reason="insufficient_funds")
    issues = detect_systemic_issues(df)
    assert issues == {}  # insufficient_funds isn't in INFRA_FAILURE_REASONS


def test_empty_batch_returns_no_issues():
    df = pd.DataFrame(columns=["payment_method", "failure_reason", "days_since_event"])
    assert detect_systemic_issues(df) == {}
