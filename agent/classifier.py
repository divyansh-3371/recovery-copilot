"""
Recoverability classifier.

Trains a small, fully interpretable model (logistic regression over one-hot +
numeric features) on a *historical* batch of resolved at-risk events, then
scores today's *live* batch for P(recoverable). Interpretable-by-design: for
any single transaction we can list exactly which factors pushed the score up
or down, which the dashboard surfaces as "why the agent thinks this."

In production this would train on a merchant's real resolved-transaction
history. Here we simulate that history with data/generate_data.py using a
different seed/size than the live batch, and derive historical ground-truth
outcomes by sampling from the (hidden) true recoverability prior -- i.e. we
are simulating "what actually happened to similar past cases."
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from agent.features import CATEGORICAL_COLS, NUMERIC_COLS, build_features

HISTORICAL_SEED = 7
HISTORICAL_N = 3000


class RecoverabilityModel:
    def __init__(self) -> None:
        self._pipeline: Pipeline | None = None
        self._feature_names: list[str] | None = None

    def fit(self, historical_df: pd.DataFrame) -> "RecoverabilityModel":
        X = build_features(historical_df)
        rng = np.random.default_rng(HISTORICAL_SEED)
        y = rng.binomial(1, historical_df["_true_recoverable_prob"].to_numpy())

        pre = ColumnTransformer(
            transformers=[
                ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_COLS),
                ("num", StandardScaler(), NUMERIC_COLS),
            ]
        )
        clf = LogisticRegression(max_iter=1000)
        self._pipeline = Pipeline([("pre", pre), ("clf", clf)])
        self._pipeline.fit(X, y)
        self._feature_names = list(self._pipeline.named_steps["pre"].get_feature_names_out())
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        assert self._pipeline is not None, "call .fit() first"
        X = build_features(df)
        return self._pipeline.predict_proba(X)[:, 1]

    def explain(self, row: pd.Series, top_k: int = 3) -> list[tuple[str, float]]:
        """Returns the top_k (feature, contribution) pairs driving this row's
        score, sorted by absolute impact. contribution = coef * scaled_value."""
        assert self._pipeline is not None, "call .fit() first"
        X = build_features(pd.DataFrame([row]))
        pre = self._pipeline.named_steps["pre"]
        clf = self._pipeline.named_steps["clf"]
        x_vec = pre.transform(X)
        x_vec = np.asarray(x_vec.todense()) if hasattr(x_vec, "todense") else np.asarray(x_vec)
        contributions = (x_vec[0] * clf.coef_[0])
        order = np.argsort(-np.abs(contributions))[:top_k]
        return [(self._feature_names[i], float(contributions[i])) for i in order]


def train_default_model() -> RecoverabilityModel:
    """Convenience: generate the simulated historical batch and fit a model on it."""
    from data.generate_data import generate

    historical_df = generate(n=HISTORICAL_N, seed=HISTORICAL_SEED)
    return RecoverabilityModel().fit(historical_df)
