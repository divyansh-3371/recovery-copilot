"""Tests for the intervention cost model -- what closes criterion 5's
"cost of intervention" requirement in the proof layer."""
from agent.cost_model import BASELINE_ACTION_COST, estimate_cost
from agent.policy import Decision


def _decision(action: str, channel: str | None = None) -> Decision:
    return Decision(transaction_id="txn_test", action=action, channel=channel)


def test_stop_has_zero_cost():
    assert estimate_cost(_decision("STOP")) == 0.0


def test_retry_payment_has_gateway_cost():
    assert estimate_cost(_decision("RETRY_PAYMENT")) > 0


def test_human_escalation_is_the_most_expensive_action():
    human_cost = estimate_cost(_decision("ESCALATE_HUMAN"))
    for action, channel in [("RETRY_PAYMENT", None), ("SEND_MESSAGE", "sms"), ("ESCALATE_OPS", None)]:
        assert human_cost > estimate_cost(_decision(action, channel))


def test_message_cost_varies_by_channel():
    sms_cost = estimate_cost(_decision("SEND_MESSAGE", "sms"))
    voice_cost = estimate_cost(_decision("SEND_MESSAGE", "voice_call"))
    assert voice_cost > sms_cost


def test_baseline_cost_is_flat_and_positive():
    assert BASELINE_ACTION_COST > 0
