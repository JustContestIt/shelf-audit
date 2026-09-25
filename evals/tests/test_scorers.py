"""The new scorer agrees with the old one (bench/score_runs.py) on every recorded IMG_0644 run."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend"))

from evals.scorers.align import align_shelf  # noqa: E402
from evals.scorers.metrics import aggregate, score_frame  # noqa: E402

GT = json.loads((REPO / "evals" / "golden" / "IMG_0644.json").read_text(encoding="utf-8"))
RUNS = REPO / "backend" / "tests" / "fixtures" / "n8n_runs"


def legacy():
    spec = importlib.util.spec_from_file_location("legacy_score_runs", REPO / "evals" / "history" / "legacy_score_runs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_same_subtype_errors_as_legacy_scorer():
    old = legacy()
    compared = 0
    for f in sorted(RUNS.glob("*.json")):
        if f.name == "INDEX.json":
            continue
        run = json.loads(f.read_text(encoding="utf-8"))
        if run["frame"] != "IMG_0644":
            continue
        for key in ("pass1", "pass2"):
            node = run.get(key)
            if not node or "_detect" not in node:
                continue
            o = old.score(node)
            if o is None or o[0] is None:
                continue
            new = score_frame(node["_detect"]["boxes_raw"], GT)
            assert new["subtype_errors"] == o[0], f"{f.name}/{key}: new {new['subtype_errors']} vs legacy {o[0]}"
            assert new["contamination"] == o[2], f"{f.name}/{key}"
            compared += 1
    assert compared >= 40


def test_alignment_cases():
    g = [{"brand": "ЧУЖОЙ"}, {"brand": "AI TEA", "subtype": "A"}, {"brand": "AI TEA", "subtype": "B"}]
    box = lambda x, sub, label="AI TEA": {"box_2d": [0, x, 10, x + 5], "label": label, "subtype": sub}  # noqa: E731
    a = align_shelf([box(10, "A"), box(20, "B")], g)
    assert a.target == "own" and a.lost == 0 and all(p["subtype"] == q["subtype"] for p, q in a.pairs)
    a = align_shelf([box(0, "Z"), box(10, "A"), box(20, "B")], g)  # competitor counted as ours
    assert a.target == "all"
    r = score_frame([box(0, "Z"), box(10, "A"), box(20, "B")], {"frame_id": "x", "tier": "gold",
                    "shelves": [{"shelf_index": 1, "units": g, "units_gt": 2}]})
    assert r["contamination"] == 0  # shelf_index missing in boxes -> nothing mapped
    b = [dict(bb, shelf_index=1) for bb in (box(0, "Z"), box(10, "A"), box(20, "B"))]
    r = score_frame(b, {"frame_id": "x", "tier": "gold", "shelves": [{"shelf_index": 1, "units": g, "units_gt": 2}]})
    assert r["contamination"] == 1 and r["subtype_errors"] == 0 and not r["per_shelf"][0]["count_exact"]
    s = aggregate([{"frame_id": "x", "variant": "orig", "tier": "gold", "score": r, "cost_usd": 0.1, "latency_s": 50}])
    assert s["contamination"] == 1 and s["count_exact_shelf_rate"] == 0
