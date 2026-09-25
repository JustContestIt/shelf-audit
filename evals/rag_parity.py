#!/usr/bin/env python3
"""pgvector vs the in-memory snapshot: the same top-k for the same crops?

The graph uses pgvector when DATABASE_URL is set and the .npz snapshot otherwise (tests, offline).
Both must give the same answer, or evals run offline would not describe production. Queries: the
129 labelled units of rag_sanity.py, production settings (brand filter AI TEA, ревень excluded,
default stage-1 limit, k=3).

    DATABASE_URL=postgresql://... python evals/rag_parity.py     # after `make index`
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO))

from app.config import get_settings  # noqa: E402
from app.rag.embed import get_siglip  # noqa: E402
from app.rag.index import MemoryIndex, PgVectorIndex  # noqa: E402
from app.rag.retrieve import Retriever  # noqa: E402
from app.vision.crops import crop_xyxy_px, load_image  # noqa: E402
from evals.rag_sanity import load_units  # noqa: E402


def main() -> int:
    s = get_settings()
    if not s.database_url:
        print("!! DATABASE_URL is not set")
        return 2
    pg = PgVectorIndex(s.database_url)
    snap = Path(s.catalog_path).parent / "index.npz"
    if pg.count() == 0 or not snap.exists():
        print("!! run `make index` first (pgvector table and data/catalog/index.npz)")
        return 2
    mem = MemoryIndex.load(snap)
    siglip = get_siglip()
    frames = s.data_dir / "frames" / "examples"
    units, images = load_units(), {}
    crops = []
    for u in units:
        if u["photo"] not in images:
            images[u["photo"]] = load_image(frames / f"{u['photo']}.JPG")
        crops.append(crop_xyxy_px(images[u["photo"]], u["box"]))
    r_pg, r_mem = Retriever(pg, siglip), Retriever(mem, siglip)
    same_top1 = same_top3 = 0
    diffs = []
    max_score_diff = 0.0
    for u, crop in zip(units, crops, strict=True):
        a = r_pg.retrieve([crop], brand="AI TEA", k=3, exclude_keys=s.exclude_keys)
        b = r_mem.retrieve([crop], brand="AI TEA", k=3, exclude_keys=s.exclude_keys)
        na, nb = [c.canon_name for c in a.candidates], [c.canon_name for c in b.candidates]
        same_top1 += bool(na) and bool(nb) and na[0] == nb[0]
        same_top3 += na == nb
        for ca, cb in zip(a.candidates, b.candidates, strict=False):
            if ca.canon_name == cb.canon_name:
                max_score_diff = max(max_score_diff, abs(ca.score - cb.score))
        if na != nb:
            diffs.append({"photo": u["photo"], "gt": u["gt"], "pgvector": na, "memory": nb})
    n = len(units)
    print(f"queries {n}: same top-1 {same_top1}/{n}, same top-3 list {same_top3}/{n}, max score diff {max_score_diff:.2e}")
    res = {"name": "rag_parity", "created_at": datetime.now(UTC).isoformat(timespec="seconds"), "mode": "offline",
           "config": {"backend_a": "pgvector (HNSW)", "backend_b": "memory (.npz)", "siglip": siglip is not None,
                      "brand": "AI TEA", "exclude_keys": s.exclude_keys, "k": 3, "refs": pg.count()},
           "summary": {"n_queries": n, "same_top1": same_top1, "same_top3": same_top3,
                       "max_score_diff": round(max_score_diff, 6)},
           "per_frame": diffs, "notes": "Queries = the 129 labelled units of rag_sanity.py."}
    out = REPO / "evals" / "results" / f"rag_parity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out}")
    return 0 if same_top3 == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
