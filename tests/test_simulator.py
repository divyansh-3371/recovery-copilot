"""Tests for the outcome simulator's aggregate math -- the numbers that
back the "measured money recovered" claim on the dashboard."""
import pandas as pd

from agent.simulator import summarize


def test_summarize_uplift_math():
    results = pd.DataFrame([
        {"amount": 1000.0, "agent_recovered_amount": 1000.0, "baseline_recovered_amount": 0.0,
         "promise_to_pay_status": "not_applicable", "baseline_compliance_violation": None},
        {"amount": 2000.0, "agent_recovered_amount": 0.0, "baseline_recovered_amount": 2000.0,
         "promise_to_pay_status": "kept", "baseline_compliance_violation": "contacted a do-not-contact customer"},
    ])
    summary = summarize(results)
    assert summary["total_at_risk"] == 3000.0
    assert summary["agent_recovered"] == 1000.0
    assert summary["baseline_recovered"] == 2000.0
    assert summary["uplift_amount"] == -1000.0
    assert summary["baseline_compliance_violations_avoided"] == 1
    assert summary["promises_kept"] == 1
    assert summary["promises_broken"] == 0
    assert summary["n_transactions"] == 2


def test_summarize_handles_zero_baseline_recovery():
    results = pd.DataFrame([
        {"amount": 500.0, "agent_recovered_amount": 500.0, "baseline_recovered_amount": 0.0,
         "promise_to_pay_status": "not_applicable", "baseline_compliance_violation": None},
    ])
    summary = summarize(results)
    assert summary["agent_recovery_rate"] == 100.0
    assert summary["baseline_recovery_rate"] == 0.0
