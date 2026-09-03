"""Shared feature engineering — used identically at training time and at
scoring time so the live batch is featurized exactly like the historical
data the model was trained on."""
from __future__ import annotations

import numpy as np
import pandas as pd

CATEGORICAL_COLS = ["risk_type", "failure_reason", "payment_method", "customer_segment"]
NUMERIC_COLS = ["amount_log", "previous_attempts", "days_since_event", "customer_local_hour", "do_not_contact_flag"]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["amount_log"] = np.log1p(out["amount"])
    out["do_not_contact_flag"] = out["do_not_contact"].astype(int)
    return out[CATEGORICAL_COLS + NUMERIC_COLS]
