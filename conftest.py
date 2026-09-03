"""Ensures the repo root is importable as `agent.*` / `data.*` regardless of
how pytest is invoked (bare `pytest`, `python -m pytest`, from a subdirectory,
or from CI)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
