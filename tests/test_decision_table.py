"""Tests for the failure-reason decision table -- the single source of
truth policy.py, retry_sequencer.py, and simulator.py all consult."""
from agent.decision_table import (
    COMPLIANCE_REVIEW_REASONS,
    CUSTOMER_ACTION_REASONS,
    MANDATE_REASONS,
    RETRY_FRIENDLY_REASONS,
    get_config,
)


def test_known_reason_returns_its_config():
    cfg = get_config("bank_timeout")
    assert cfg.category == "transient_infra"
    assert cfg.blind_retry_effective is True
    assert cfg.first_retry_delay_hours == 0.5


def test_unknown_reason_falls_back_to_safe_default():
    cfg = get_config("some_reason_nobody_has_seen_before")
    assert cfg.category == "customer_action_required"
    assert cfg.blind_retry_effective is False
    assert cfg.first_retry_delay_hours is None


def test_risk_block_is_a_compliance_review_reason_never_retry_friendly():
    assert "risk_block" in COMPLIANCE_REVIEW_REASONS
    assert "risk_block" not in RETRY_FRIENDLY_REASONS
    assert "risk_block" not in CUSTOMER_ACTION_REASONS


def test_card_reasons_are_customer_action_required():
    assert "card_expired" in CUSTOMER_ACTION_REASONS
    assert "wrong_cvv" in CUSTOMER_ACTION_REASONS


def test_mandate_reasons_are_flagged_as_mandate():
    assert {"mandate_expired", "mandate_insufficient_funds", "mandate_bank_error"} <= MANDATE_REASONS


def test_transient_infra_reasons_are_retry_friendly():
    assert "bank_timeout" in RETRY_FRIENDLY_REASONS
    assert "network_drop" in RETRY_FRIENDLY_REASONS


def test_insufficient_funds_is_retry_friendly_but_slower():
    """Retry-friendly (a retry CAN work), but only after the balance/salary
    cycle catches up -- not immediately, unlike a transient infra blip."""
    cfg = get_config("insufficient_funds")
    assert cfg.blind_retry_effective is True
    assert cfg.first_retry_delay_hours == 24.0
