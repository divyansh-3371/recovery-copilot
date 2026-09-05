"""
CLI entry point — runs the full Recovery Copilot pipeline on a fresh
synthetic batch and prints the measured recovery summary. Useful for a quick
sanity check and as a demo fallback if the dashboard has any hiccup live.

Usage:
    python run_batch.py
"""
from __future__ import annotations

import pandas as pd

from agent.pipeline import run_pipeline
from data.generate_data import generate


def main() -> None:
    print("Generating synthetic at-risk batch...")
    df = generate()

    print("Training recoverability model on simulated historical data...")
    print("Running Recovery Copilot pipeline (classify -> root-cause -> decide -> audit -> simulate)...")
    results, summary, model, systemic_issues = run_pipeline(df)

    results.to_csv("data/results.csv", index=False)

    print("\n=== Systemic issues detected ===")
    if systemic_issues:
        for issue in systemic_issues.values():
            print(f"  - {issue.note}")
    else:
        print("  (none this batch)")

    print("\n=== Action breakdown ===")
    print(results["agent_action"].value_counts().to_string())

    print("\n=== Measured recovery summary ===")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k}: {v:,.2f}")
        else:
            print(f"  {k}: {v}")

    print(f"\nWrote {len(results)} rows to data/results.csv")
    print("Audit trail written to data/audit_log.jsonl")


if __name__ == "__main__":
    pd.set_option("display.width", 120)
    main()
