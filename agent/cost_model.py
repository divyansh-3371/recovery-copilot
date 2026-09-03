"""
Estimated cost per intervention -- what it actually costs to attempt a
recovery, so the proof layer can report NET recovered (₹ recovered minus ₹
spent recovering it), not just gross recovered. Without this, "recovered
more" can hide "recovered it more expensively than it was worth" -- exactly
what criterion 5 (the proof layer) asks for by name: "₹ recovered, recovery
rate, cost of intervention."

These are illustrative unit-cost estimates (INR), not billed rates from any
specific provider -- the point is that cost is modeled at all and varies
sensibly by action/channel, not that any single number is exact.
"""
from __future__ import annotations

from agent.policy import Decision

CHANNEL_COST = {
    "sms": 0.20,
    "whatsapp": 0.50,
    "email": 0.10,
    "voice_call": 8.00,
    "voice_hinglish": 8.00,
}

GATEWAY_RETRY_COST = 2.00      # a payment-gateway retry attempt
HUMAN_AGENT_COST = 150.00      # a human recovery agent's time for one case
OPS_ALERT_COST = 5.00          # routing a systemic issue to an ops/on-call channel

# the naive baseline (a single blind retry/reminder for everyone) -- one
# flat, generic action per transaction, regardless of outcome
BASELINE_ACTION_COST = 2.00


def estimate_cost(decision: Decision) -> float:
    if decision.action == "RETRY_PAYMENT":
        return GATEWAY_RETRY_COST
    if decision.action == "SEND_MESSAGE":
        return CHANNEL_COST.get(decision.channel, 0.20)
    if decision.action == "ESCALATE_HUMAN":
        return HUMAN_AGENT_COST
    if decision.action == "ESCALATE_OPS":
        return OPS_ALERT_COST
    return 0.0  # STOP -- no action taken, no cost incurred
