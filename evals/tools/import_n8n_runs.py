#!/usr/bin/env python3
"""Import recorded n8n WF-2 runs (bench/runs, test results) into repo fixtures.

The runs are outputs of the n8n nodes «Парсинг» (pass 1) and «Слияние» (pass 2): boxes with
coordinates and subtype names — no photos, no keys. They are used for:
  * backend/tests/fixtures/n8n_runs/*.json — regression of the Python port against n8n;
  * evals/history/n8n_runs.jsonl — "before migration" numbers in EVALS.md.

    python evals/tools/import_n8n_runs.py --source "C:/.../Artyom"
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_FIX = REPO / "backend" / "tests" / "fixtures" / "n8n_runs"


def _parse_first_json(chunk: str):
    m = re.search(r"[\[{]", chunk)
    if not m:
        return None
    o, _ = json.JSONDecoder().raw_decode(chunk[m.start():])
    return o[0] if isinstance(o, list) and o else o


def load_run(path: Path) -> tuple[dict | None, dict | None, dict]:
    """-> (pass1, pass2, meta) in n8n node-output shape (_detect/_usage/_pass2)."""
    t = path.read_text(encoding="utf-8")
    if '"_bench"' in t:
        b = (_parse_first_json(t) or {}).get("_bench") or {}

        def norm(o):
            if not o:
                return None
            d = dict(o.get("detect") or {})
            if "anchor" in d:
                d["format_geo"] = {"anchor": d.pop("anchor")}
            return {"_detect": d, "_usage": o.get("usage") or {}, "_pass2": o.get("pass2")}

        return norm(b.get("pass1")), norm(b.get("pass2")), {"exec_id": b.get("run"), "ts": b.get("ts"), "label": b.get("frame")}
    marks = [(m.start(), m.end(), int(m.group(1))) for m in re.finditer(r"PASS\s*([12])\s*:", t)]
    js = {}
    for i, (_, e, n) in enumerate(marks):
        js[n] = _parse_first_json(t[e: marks[i + 1][0] if i + 1 < len(marks) else len(t)])
    return js.get(1), js.get(2), {}


def guess_frame(p1: dict) -> str:
    boxes = (p1 or {}).get("_detect", {}).get("boxes_raw", [])
    labels = {b.get("label") for b in boxes}
    shelves = {b.get("shelf_index") for b in boxes}
    if "Буратино" in labels or max(shelves or {0}) == 4:
        return "IMG_0643"
    return "IMG_0644"  # == AITEA_5SHELF (same frame, see evals/golden/README.md)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    a = ap.parse_args()
    src = Path(a.source)
    OUT_FIX.mkdir(parents=True, exist_ok=True)
    files = sorted((src / "bench" / "runs").rglob("*.txt")) + sorted((src / "test results").glob("*.txt"))
    index = []
    for f in files:
        p1, p2, meta = load_run(f)
        if not p1:
            continue
        rel = f.relative_to(src).as_posix()
        name = re.sub(r"[^A-Za-z0-9_]+", "_", rel.replace("bench/runs/", "bench_").replace("test results/", "tr_").removesuffix(".txt")).strip("_")
        rec = {"source": rel, "frame": guess_frame(p1), **meta, "pass1": p1, "pass2": p2}
        (OUT_FIX / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({"name": name, "source": rel, "frame": rec["frame"], "has_items": "items" in p1,
                      "has_slivers": "slivers_raw" in (p1.get("_detect") or {})})
    (OUT_FIX / "INDEX.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(index)} runs -> {OUT_FIX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
