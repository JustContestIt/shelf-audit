"""Positional alignment of predicted boxes to the GT sequence of a shelf.

Units are ordered left to right (pred: by box x_min). Candidate GT targets are the full
sequence (our + foreign units) and our units only (foreign not boxed — the normal case).
If lengths differ by at most 2, every way of dropping the surplus from the longer side is
tried and the alignment with the fewest errors wins — exactly how bench/score_runs.py
handled lost slivers and overlapped bottles, extended to extra boxes.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

FOREIGN = "ЧУЖОЙ"
MAX_GAP = 2


@dataclass
class Alignment:
    pairs: list[tuple[dict, dict]] = field(default_factory=list)  # (pred box, gt unit)
    target: str = ""            # "all" | "own" | "none"
    lost: int = 0               # GT units without a box
    extra: int = 0              # boxes without a GT unit
    aligned: bool = True


def _is_ours(b: dict) -> bool:
    return b.get("label") not in (None, FOREIGN)


def _err(p: dict, g: dict) -> int:
    if g["brand"] == FOREIGN:
        return 2 if _is_ours(p) else 0  # counting a competitor as ours is the worst error
    if not _is_ours(p):
        return 1
    return int((p.get("subtype") or None) != (g.get("subtype") or None))


def _best(pred: list[dict], gt: list[dict]) -> tuple[list[tuple[dict, dict]], int, int, int]:
    """Drop surplus from the longer side; returns (pairs, errors, lost, extra)."""
    k = len(gt) - len(pred)
    if k == 0:
        pairs = list(zip(pred, gt, strict=True))
        return pairs, sum(_err(p, g) for p, g in pairs), 0, 0
    best = None
    if k > 0:
        for drop in itertools.combinations(range(len(gt)), k):
            sub = [g for i, g in enumerate(gt) if i not in drop]
            e = sum(_err(p, g) for p, g in zip(pred, sub, strict=True))
            if best is None or e < best[1]:
                best = (list(zip(pred, sub, strict=True)), e, k, 0)
    else:
        for drop in itertools.combinations(range(len(pred)), -k):
            sub = [p for i, p in enumerate(pred) if i not in drop]
            e = sum(_err(p, g) for p, g in zip(sub, gt, strict=True)) + (-k)
            if best is None or e < best[1]:
                best = (list(zip(sub, gt, strict=True)), e, 0, -k)
    return best


def align_shelf(pred: list[dict], gt_units: list[dict]) -> Alignment:
    pred = sorted(pred, key=lambda b: b["box_2d"][1])
    ours = [b for b in pred if _is_ours(b)]
    own = [u for u in gt_units if u["brand"] != FOREIGN]
    options = []
    for name, p, g in (("all", pred, gt_units), ("own", ours, own)):
        if abs(len(g) - len(p)) <= MAX_GAP and len(g) and len(p):
            pairs, e, lost, extra = _best(p, g)
            options.append((abs(len(g) - len(p)), e, name, pairs, lost, extra))
    if not options:
        return Alignment(target="none", aligned=False, lost=max(0, len(own) - len(ours)), extra=max(0, len(ours) - len(own)))
    _, _, name, pairs, lost, extra = min(options, key=lambda o: (o[0], o[1]))
    return Alignment(pairs=pairs, target=name, lost=lost, extra=extra)
