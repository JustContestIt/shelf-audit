"""Scorers of the shelf-audit eval framework.

align    — positional alignment of predicted units to GT units inside a shelf (port and
           generalisation of bench/score_runs.py: 1:1, own-only, 1–2 lost/extra units).
metrics  — per-shelf / per-frame metrics and aggregation into the summary:
           count accuracy + MAE, subtype accuracy (+ pink zone), contamination, pack accuracy,
           stability (σ over repeats), cost and latency, guardrail precision/recall.
No LLM-as-judge: the GT is exact, a judge would only add noise (EVALS.md).
"""
