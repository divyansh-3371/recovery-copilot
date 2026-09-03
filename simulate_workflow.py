"""
CLI: runs the multi-day workflow simulation and prints the day-by-day
recovery curve -- proof that "executes a bounded recovery workflow" means
state persisting and decisions evolving over time, not one stateless pass.

Usage:
    python simulate_workflow.py [--days 5]
"""
from __future__ import annotations

import argparse

from agent.classifier import train_default_model
from agent.workflow import run_workflow
from data.generate_data import generate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Generating synthetic batch (seed={args.seed})...")
    df = generate(seed=args.seed)

    print("Training recoverability model...")
    model = train_default_model()

    print(f"Simulating {args.days}-day recovery workflow...")
    daily = run_workflow(df, model, n_days=args.days)
    daily.to_csv("data/workflow_daily_summary.csv", index=False)

    print("\n=== Day-by-day recovery curve ===")
    print(daily.to_string(index=False))

    last = daily.iloc[-1]
    print(f"\nFinal: {int(last['cumulative_resolved'])} transactions resolved, "
          f"Rs.{last['cumulative_recovered']:,.0f} recovered across {len(daily)} simulated days.")
    print("Audit trail: data/workflow_audit_log.jsonl")


if __name__ == "__main__":
    main()
