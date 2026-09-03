"""Tests for the recoverability classifier: trains fast on a small synthetic
history and checks the score + explanation contract, not exact values."""
import pandas as pd

from agent.classifier import RecoverabilityModel
from data.generate_data import generate


def _small_model() -> RecoverabilityModel:
    historical = generate(n=300, seed=1)
    return RecoverabilityModel().fit(historical)


def test_predict_proba_returns_valid_probabilities():
    model = _small_model()
    live = generate(n=50, seed=2)
    scores = model.predict_proba(live)
    assert len(scores) == len(live)
    assert ((scores >= 0.0) & (scores <= 1.0)).all()


def test_explain_returns_top_k_signed_contributions():
    model = _small_model()
    live = generate(n=5, seed=3)
    row = live.iloc[0]
    contributions = model.explain(row, top_k=3)
    assert len(contributions) == 3
    for feature_name, value in contributions:
        assert isinstance(feature_name, str)
        assert isinstance(value, float)
