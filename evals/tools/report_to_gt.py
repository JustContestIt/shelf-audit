#!/usr/bin/env python3
"""Semi-automatic labelling: an approved / corrected report of the cabinet -> a golden frame.

Workflow from the plan: run the graph on a new frame -> fix subtypes/counts in the review screen
(«Исправить») -> approve -> this script turns the reviewed boxes into evals/golden/<frame>.json
(tier "silver-reviewed"). The frame must also be copied into data/frames/.

    python evals/tools/report_to_gt.py --report R_2026... --frame-id FIELD_0101 --file frames/new/IMG_0101.JPG
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
FOREIGN = "ЧУЖОЙ"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--frame-id", required=True)
    ap.add_argument("--file", required=True, help="path of the frame relative to data/")
    ap.add_argument("--api", default=os.environ.get("API_BASE_URL", "http://localhost:8000"))
    a = ap.parse_args()
    headers = {"Authorization": f"Bearer {os.environ['API_TOKEN']}"} if os.environ.get("API_TOKEN") else {}
    rec = httpx.get(f"{a.api}/reports/{a.report}", headers=headers, timeout=30).json()
    if rec["status"] not in ("approved", "edited"):
        raise SystemExit(f"report status is {rec['status']}: approve or correct it in the cabinet first")
    body = rec["body"]
    rows = body["report"]["rows"]
    # corrected rows are the truth for counts/subtypes; boxes give the left-to-right order inside a shelf
    boxes = sorted((b for b in body["boxes"] if b.get("label") not in (None,)), key=lambda b: (b["shelf_index"], b["box_2d"][1]))
    shelves: dict[int, list[dict]] = {}
    for b in boxes:
        shelves.setdefault(b["shelf_index"], []).append(
            {"brand": b["label"] if b["label"] != FOREIGN else FOREIGN, "subtype": b.get("subtype"), "format": b.get("format")})
    for si, units in shelves.items():
        want = sum(r["front_facing_count"] for r in rows if r["shelf_index"] == si)
        have = sum(1 for u in units if u["brand"] != FOREIGN)
        if want != have:
            print(f"! shelf {si}: reviewed count {want} != boxes {have} — edit the JSON by hand (order unknown)")
    frame = {"frame_id": a.frame_id, "aliases": [], "tier": "silver-reviewed", "file": a.file, "size": None,
             "variants": ["orig", "tg1280"], "source": f"report {a.report} reviewed by {(rec.get('review') or {}).get('reviewer')}",
             "notes": "Semi-automatic GT: model boxes + supervisor corrections. Check positions once more before use as gold.",
             "shelves": [{"shelf_index": si, "units": u, "units_gt": sum(1 for x in u if x["brand"] != FOREIGN), "tags": []}
                         for si, u in sorted(shelves.items())]}
    out = REPO / "evals" / "golden" / f"{a.frame_id}.json"
    out.write_text(json.dumps(frame, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out}; add it to evals/golden/INDEX.json (or rerun build_golden.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
