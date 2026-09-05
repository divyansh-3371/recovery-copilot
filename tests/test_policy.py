"""Tests for the decision engine's stopping rules and routing -- the module
that answers the buildathon's "compliant escalation with stopping rules" bar.
Every rule here must be checked BEFORE any customer-facing action."""
from helpers import make_row

from agent.policy import decide


def test_do_not_contact_always_stops():
    row = make_row(do_not_contact=True)
    d = decide(row, score=0.95, systemic_issues={})
    assert d.action == "STOP"
    assert d.stopping_rule_triggered == "do_not_contact"


def test_max_attempts_cap_stops_even_with_high_score():
    row = make_row(previous_attempts=3)
    d = decide(row, score=0.95, systemic_issues={})
    assert d.action == "STOP"
    assert d.stopping_rule_triggered == "max_attempts_reached"


def test_uneconomical_amount_stops_for_returning_customer():
    # Returning: already acquired, no sunk-CAC recapture argument for a
    # tiny amount -- the one segment with no exemption from this floor.
    row = make_row(amount=50.0, customer_segment="returning")
    d = decide(row, score=0.95, systemic_issues={})
    assert d.action == "STOP"
    assert d.stopping_rule_triggered == "uneconomical_amount"


def test_uneconomical_amount_floor_does_not_apply_to_new_customer():
    # New: the sunk acquisition-cost argument applies here too, same as
    # the low-score branch -- a tiny amount alone shouldn't stop this.
    row = make_row(amount=50.0, customer_segment="new", risk_type="payment_failure",
                    failure_reason="bank_timeout")
    d = decide(row, score=0.95, systemic_issues={})
    assert d.stopping_rule_triggered != "uneconomical_amount"


def test_uneconomical_amount_floor_does_not_apply_to_vip():
    row = make_row(amount=50.0, customer_segment="vip", risk_type="payment_failure",
                    failure_reason="bank_timeout")
    d = decide(row, score=0.95, systemic_issues={})
    assert d.stopping_rule_triggered != "uneconomical_amount"


def test_systemic_issue_routes_to_escalate_ops_not_customer_contact():
    row = make_row(payment_method="netbanking", failure_reason="bank_timeout")
    from agent.root_cause import SystemicIssue
    issue = SystemicIssue(payment_method="netbanking", failure_reason="bank_timeout",
                           recent_count=30, recent_rate_per_day=30.0, baseline_rate_per_day=1.0, ratio=30.0)
    d = decide(row, score=0.9, systemic_issues={("netbanking", "bank_timeout"): issue})
    assert d.action == "ESCALATE_OPS"
    assert d.channel is None  # never contacts the customer for a systemic issue


def test_card_expired_never_gets_a_blind_retry():
    row = make_row(failure_reason="card_expired", risk_type="payment_failure")
    d = decide(row, score=0.9, systemic_issues={})
    assert d.action == "SEND_MESSAGE"  # asks the customer to update their card, not a silent retry


def test_high_score_payment_failure_retries():
    row = make_row(risk_type="payment_failure", failure_reason="bank_timeout", previous_attempts=0)
    d = decide(row, score=0.8, systemic_issues={})
    assert d.action == "RETRY_PAYMENT"
    assert d.retry_delay_hours is not None


def test_low_score_low_value_stops_for_returning_customer():
    # A returning customer has already been acquired -- no sunk-CAC argument
    # for a genuinely low-probability, low-value case, so stopping is right.
    row = make_row(amount=500.0, customer_segment="returning")
    d = decide(row, score=0.1, systemic_issues={})
    assert d.stopping_rule_triggered == "low_confidence_low_value"


def test_low_score_new_customer_still_gets_a_cheap_nudge_not_a_stop():
    # A new customer's low score doesn't mean "not worth it" the way a
    # returning customer's does -- the merchant already spent real
    # acquisition cost getting them to a checkout, sunk whether we try or
    # not, so a cheap nudge (not a human agent) is still worth it here.
    row = make_row(amount=500.0, customer_segment="new")
    d = decide(row, score=0.1, systemic_issues={})
    assert d.action == "SEND_MESSAGE"
    assert d.stopping_rule_triggered is None


def test_low_score_high_value_escalates_to_human():
    row = make_row(amount=50000.0, customer_segment="returning")
    d = decide(row, score=0.1, systemic_issues={})
    assert d.action == "ESCALATE_HUMAN"


def test_quiet_hours_defers_message_send():
    row = make_row(customer_local_hour=2, risk_type="checkout_abandonment",
                    failure_reason="cart_abandoned_otp", previous_attempts=0)
    d = decide(row, score=0.5, systemic_issues={})
    if d.action == "SEND_MESSAGE":
        assert d.scheduled_hour == 9


def test_every_decision_carries_reasoning():
    row = make_row()
    d = decide(row, score=0.5, systemic_issues={})
    assert len(d.reasoning) > 0


def test_risk_block_never_auto_retried_or_messaged():
    """A risk/fraud-engine block must always go to human review -- never a
    blind retry (looks like fraud evasion) and never a customer message
    (the customer isn't the one who can fix a risk-engine decision)."""
    row = make_row(failure_reason="risk_block", risk_type="payment_failure")
    d = decide(row, score=0.9, systemic_issues={})
    assert d.action == "ESCALATE_HUMAN"
    assert d.channel is None


def test_risk_block_still_respects_stopping_rules_first():
    row = make_row(failure_reason="risk_block", risk_type="payment_failure", do_not_contact=True)
    d = decide(row, score=0.9, systemic_issues={})
    assert d.action == "STOP"
    assert d.stopping_rule_triggered == "do_not_contact"


# --- cost-aware value triage -------------------------------------------------

def test_value_triage_overrides_card_update_reason():
    """card_expired normally gets a SEND_MESSAGE (ask the customer to
    update their card) -- at high enough value, a human reviews it instead,
    regardless of that failure-reason mapping."""
    row = make_row(failure_reason="card_expired", risk_type="payment_failure", amount=100_000.0)
    d = decide(row, score=0.9, systemic_issues={})
    assert d.action == "ESCALATE_HUMAN"
    assert "value-triage" in " ".join(d.reasoning).lower()


def test_value_triage_overrides_automated_retry():
    """bank_timeout at high score normally gets an automated RETRY_PAYMENT --
    at high enough value, a human reviews it instead."""
    row = make_row(failure_reason="bank_timeout", risk_type="payment_failure", amount=200_000.0)
    d = decide(row, score=0.9, systemic_issues={})
    assert d.action == "ESCALATE_HUMAN"


def test_value_triage_does_not_apply_below_threshold():
    """Just under the threshold, normal failure-reason routing still applies."""
    row = make_row(failure_reason="card_expired", risk_type="payment_failure", amount=74_999.0)
    d = decide(row, score=0.9, systemic_issues={})
    assert d.action == "SEND_MESSAGE"


def test_value_triage_never_overrides_do_not_contact():
    row = make_row(amount=500_000.0, do_not_contact=True)
    d = decide(row, score=0.9, systemic_issues={})
    assert d.action == "STOP"
    assert d.stopping_rule_triggered == "do_not_contact"


def test_collections_routes_severely_overdue_high_value_invoice():
    row = make_row(risk_type="invoice_overdue", failure_reason="invoice_overdue_45plus", amount=20_000.0)
    d = decide(row, score=0.5, systemic_issues={})
    assert d.action == "ESCALATE_COLLECTIONS"


def test_collections_does_not_apply_below_its_threshold():
    """A small severely-overdue invoice still isn't worth formal
    collections -- falls through to the normal reason/score-based routing."""
    row = make_row(risk_type="invoice_overdue", failure_reason="invoice_overdue_45plus", amount=5_000.0)
    d = decide(row, score=0.5, systemic_issues={})
    assert d.action != "ESCALATE_COLLECTIONS"


def test_collections_does_not_apply_to_other_overdue_tiers():
    """Only the 45+ day tier goes to collections -- 15/30 day overdue
    invoices are still just a follow-up nudge, not formal collections."""
    row = make_row(risk_type="invoice_overdue", failure_reason="invoice_overdue_15d", amount=20_000.0)
    d = decide(row, score=0.5, systemic_issues={})
    assert d.action != "ESCALATE_COLLECTIONS"


def test_collections_beats_generic_value_triage_when_both_apply():
    """A severely overdue invoice big enough to also clear the generic
    value-triage threshold should still get the more specific collections
    routing, not the generic human-escalation one."""
    row = make_row(risk_type="invoice_overdue", failure_reason="invoice_overdue_45plus", amount=200_000.0)
    d = decide(row, score=0.5, systemic_issues={})
    assert d.action == "ESCALATE_COLLECTIONS"


def test_collections_still_respects_stopping_rules_first():
    row = make_row(risk_type="invoice_overdue", failure_reason="invoice_overdue_45plus",
                    amount=200_000.0, do_not_contact=True)
    d = decide(row, score=0.5, systemic_issues={})
    assert d.action == "STOP"
    assert d.stopping_rule_triggered == "do_not_contact"


def test_value_triage_never_overrides_systemic_issue_routing():
    """A genuine bank-side outage still routes to ops, not a human agent,
    even for a large amount -- the fix there is operational, not a bigger
    escalation ladder."""
    row = make_row(amount=500_000.0, payment_method="netbanking", failure_reason="bank_timeout")
    from agent.root_cause import SystemicIssue
    issue = SystemicIssue(payment_method="netbanking", failure_reason="bank_timeout",
                           recent_count=30, recent_rate_per_day=30.0, baseline_rate_per_day=1.0, ratio=30.0)
    d = decide(row, score=0.9, systemic_issues={("netbanking", "bank_timeout"): issue})
    assert d.action == "ESCALATE_OPS"


def test_systemic_issue_overrides_do_not_contact():
    """Outage detection never contacts the customer either -- a
    do-not-contact flag shouldn't hide a real infra problem from ops."""
    row = make_row(payment_method="netbanking", failure_reason="bank_timeout", do_not_contact=True)
    from agent.root_cause import SystemicIssue
    issue = SystemicIssue(payment_method="netbanking", failure_reason="bank_timeout",
                           recent_count=30, recent_rate_per_day=30.0, baseline_rate_per_day=1.0, ratio=30.0)
    d = decide(row, score=0.9, systemic_issues={("netbanking", "bank_timeout"): issue})
    assert d.action == "ESCALATE_OPS"


def test_systemic_issue_overrides_uneconomical_amount():
    """A tiny transaction failing during a genuine outage must still
    surface to ops -- outage visibility can't depend on this one
    transaction's economics."""
    row = make_row(amount=10.0, payment_method="netbanking", failure_reason="bank_timeout")
    from agent.root_cause import SystemicIssue
    issue = SystemicIssue(payment_method="netbanking", failure_reason="bank_timeout",
                           recent_count=30, recent_rate_per_day=30.0, baseline_rate_per_day=1.0, ratio=30.0)
    d = decide(row, score=0.9, systemic_issues={("netbanking", "bank_timeout"): issue})
    assert d.action == "ESCALATE_OPS"


def test_max_attempts_escalates_to_human_for_vip():
    row = make_row(previous_attempts=3, customer_segment="vip")
    d = decide(row, score=0.95, systemic_issues={})
    assert d.action == "ESCALATE_HUMAN"
    assert d.stopping_rule_triggered is None


def test_max_attempts_escalates_to_human_for_high_value():
    row = make_row(previous_attempts=3, amount=50_000.0, customer_segment="returning")
    d = decide(row, score=0.95, systemic_issues={})
    assert d.action == "ESCALATE_HUMAN"
    assert d.stopping_rule_triggered is None


def test_max_attempts_still_stops_for_low_value_returning_customer():
    row = make_row(previous_attempts=3, amount=2000.0, customer_segment="returning")
    d = decide(row, score=0.95, systemic_issues={})
    assert d.action == "STOP"
    assert d.stopping_rule_triggered == "max_attempts_reached"
