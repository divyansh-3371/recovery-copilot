"""Shared test fixtures: a sane-default transaction row, overridable per test."""
import pandas as pd

DEFAULTS = dict(
    transaction_id="txn_test_0001",
    customer_id="cust_00001",
    customer_name="Test Customer",
    amount=2000.0,
    currency="INR",
    risk_type="payment_failure",
    failure_reason="bank_timeout",
    payment_method="netbanking",
    customer_segment="returning",
    previous_attempts=0,
    do_not_contact=False,
    customer_local_hour=12,
    days_since_event=0,
    _true_recoverable_prob=0.6,
)


def make_row(**overrides) -> pd.Series:
    data = {**DEFAULTS, **overrides}
    return pd.Series(data)
