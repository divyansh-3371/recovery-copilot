"""Tests for the outcome simulator's aggregate math -- the numbers that
back the "measured money recovered" claim on the dashboard, including net
recovery after the cost of intervention (criterion 5's proof layer)."""
import pandas as pd

from agent.simulator import summarize


def test_summarize_uplift_math():
    results = pd.DataFrame([
        {"amount": 1000.0, "agent_recovered_amount": 1000.0, "baseline_recovered_amount": 0.0,
         "agent_intervention_cost": 2.0, "baseline_intervention_cost": 2.0,
         "promise_to_pay_status": "not_applicable", "baseline_compliance_violation": None},
        {"amount": 2000.0, "agent_recovered_amount": 0.0, "baseline_recovered_amount": 2000.0,
         "agent_intervention_cost": 0.0, "baseline_intervention_cost": 2.0,
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

    # cost-of-intervention / net-recovered math
    assert summary["agent_intervention_cost"] == 2.0
    assert summary["baseline_intervention_cost"] == 4.0
    assert summary["agent_net_recovered"] == 998.0       # 1000 - 2
    assert summary["baseline_net_recovered"] == 1996.0   # 2000 - 4
    assert summary["net_uplift_amount"] == 998.0 - 1996.0


def test_summarize_handles_zero_baseline_recovery():
    results = pd.DataFrame([
        {"amount": 500.0, "agent_recovered_amount": 500.0, "baseline_recovered_amount": 0.0,
         "agent_intervention_cost": 2.0, "baseline_intervention_cost": 2.0,
         "promise_to_pay_status": "not_applicable", "baseline_compliance_violation": None},
    ])
    summary = summarize(results)
    assert summary["agent_recovery_rate"] == 100.0
    assert summary["baseline_recovery_rate"] == 0.0
    assert summary["agent_net_recovered"] == 498.0
    assert summary["baseline_net_recovered"] == -2.0
