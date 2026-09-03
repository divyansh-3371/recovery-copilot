"""
Generates a synthetic batch of at-risk revenue events for Recovery Copilot.

Simulates four kinds of revenue-at-risk events that Razorpay merchants see in
production: payment failures, checkout abandonment, subscription/mandate
failures, and overdue B2B invoices. Each row also carries a hidden
`_true_recoverable_prob` used ONLY by the outcome simulator to decide whether
an intervention actually succeeds -- the agent never sees this field, it only
sees the same observable features a real system would have.

A deliberate, clearly-labeled synthetic outage (netbanking bank_timeout
spiking in the last day) is injected on top of the random batch so the
root-cause detector has something real and reproducible to catch on every
run -- the same way a monitoring-system demo seeds a known incident rather
than hoping one appears by chance.

Run directly to (re)write data/transactions.csv:
    python data/generate_data.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from faker import Faker

RNG_SEED = 42
N_TRANSACTIONS = 600
N_INJECTED_OUTAGE = 25

RISK_TYPES = ["payment_failure", "checkout_abandonment", "subscription_failure", "invoice_overdue"]
RISK_TYPE_WEIGHTS = [0.45, 0.25, 0.20, 0.10]

FAILURE_REASONS = {
    "payment_failure": [
        "insufficient_funds", "bank_timeout", "card_expired",
        "wrong_cvv", "network_drop", "issuer_declined", "risk_block",
    ],
    "checkout_abandonment": ["cart_abandoned_otp", "cart_abandoned_payment_page", "price_hesitation"],
    "subscription_failure": ["mandate_expired", "mandate_insufficient_funds", "mandate_bank_error"],
    "invoice_overdue": ["invoice_overdue_15d", "invoice_overdue_30d", "invoice_overdue_45plus"],
}

PAYMENT_METHODS = ["card", "upi", "netbanking", "wallet"]
CUSTOMER_SEGMENTS = ["new", "returning", "vip"]
SEGMENT_WEIGHTS = [0.35, 0.50, 0.15]

# the injected, reproducible "outage" the root-cause detector is meant to catch
OUTAGE_RISK_TYPE = "payment_failure"
OUTAGE_REASON = "bank_timeout"
OUTAGE_METHOD = "netbanking"


def _recoverability_prior(row: pd.Series) -> float:
    """Hidden ground-truth probability an event recovers with a *good* intervention.
    Not seen by the agent -- used only to simulate realistic outcomes."""
    base = {
        "payment_failure": 0.55,
        "checkout_abandonment": 0.35,
        "subscription_failure": 0.45,
        "invoice_overdue": 0.30,
    }[row["risk_type"]]

    reason_adj = {
        "insufficient_funds": -0.10, "bank_timeout": +0.15, "card_expired": -0.20,
        "wrong_cvv": +0.20, "network_drop": +0.20, "issuer_declined": -0.05,
        "risk_block": -0.35,
        "cart_abandoned_otp": +0.10, "cart_abandoned_payment_page": +0.05, "price_hesitation": -0.15,
        "mandate_expired": -0.10, "mandate_insufficient_funds": -0.10, "mandate_bank_error": +0.15,
        "invoice_overdue_15d": +0.15, "invoice_overdue_30d": 0.0, "invoice_overdue_45plus": -0.20,
    }.get(row["failure_reason"], 0.0)

    segment_adj = {"vip": +0.15, "returning": +0.05, "new": -0.05}[row["customer_segment"]]
    attempts_adj = -0.08 * row["previous_attempts"]
    dnc_adj = -0.9 if row["do_not_contact"] else 0.0

    p = base + reason_adj + segment_adj + attempts_adj + dnc_adj
    return float(np.clip(p, 0.02, 0.95))


def _make_row(
    i: int,
    rng: np.random.Generator,
    fake: Faker,
    rt: str | None = None,
    reason: str | None = None,
    method: str | None = None,
    days_since_event: int | None = None,
) -> dict:
    rt = rt or rng.choice(RISK_TYPES, p=RISK_TYPE_WEIGHTS)
    reason = reason or rng.choice(FAILURE_REASONS[rt])
    method = method or rng.choice(PAYMENT_METHODS)
    segment = rng.choice(CUSTOMER_SEGMENTS, p=SEGMENT_WEIGHTS)

    amount = float(np.round(np.exp(rng.normal(7.2, 1.1)), 2))  # long-tailed INR amounts
    amount = max(99.0, min(amount, 250000.0))
    if rt == "invoice_overdue":
        amount = max(amount, 5000.0)  # B2B invoices skew larger

    previous_attempts = int(rng.choice([0, 1, 2, 3], p=[0.55, 0.25, 0.13, 0.07]))
    do_not_contact = bool(rng.random() < 0.04)
    customer_local_hour = int(rng.integers(0, 24))
    if days_since_event is None:
        days_since_event = int(rng.integers(0, 10)) if rt != "invoice_overdue" else int(rng.integers(10, 60))

    row = {
        "transaction_id": f"txn_{i:05d}",
        "customer_id": f"cust_{rng.integers(0, 5000):05d}",
        "customer_name": fake.name(),
        "amount": amount,
        "currency": "INR",
        "risk_type": rt,
        "failure_reason": reason,
        "payment_method": method,
        "customer_segment": segment,
        "previous_attempts": previous_attempts,
        "do_not_contact": do_not_contact,
        "customer_local_hour": customer_local_hour,
        "days_since_event": days_since_event,
    }
    row["_true_recoverable_prob"] = _recoverability_prior(pd.Series(row))
    return row


def generate(n: int = N_TRANSACTIONS, seed: int = RNG_SEED, inject_outage: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    fake = Faker()
    Faker.seed(seed)

    rows = [_make_row(i, rng, fake) for i in range(n)]

    if inject_outage:
        for j in range(N_INJECTED_OUTAGE):
            rows.append(
                _make_row(
                    n + j, rng, fake,
                    rt=OUTAGE_RISK_TYPE, reason=OUTAGE_REASON, method=OUTAGE_METHOD,
                    days_since_event=int(rng.integers(0, 2)),  # forces it into the "recent" window
                )
            )

    df = pd.DataFrame(rows)
    df["created_at"] = pd.Timestamp.now() - pd.to_timedelta(df["days_since_event"], unit="D")
    return df


if __name__ == "__main__":
    df = generate()
    out_path = "data/transactions.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} synthetic at-risk events to {out_path}")
    print(df["risk_type"].value_counts())
