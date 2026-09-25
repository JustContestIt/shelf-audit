#!/usr/bin/env python3
"""RAG sanity test: retrieval top-1 on the 129 labelled units of the 24.08 multi-frame experiment.

Reproduces embedding_experiment/REPORT.md round 2 with the production code (app.rag.*):
crops by the experiment's boxes (multi_crops_meta.json, YOLO11x) from data/frames/examples,
labels from labels_IMG_*.json (strict units only). Expected on the "exp_current" ref set:
SigLIP+HSV ensemble ≈ 120/129 (93%), HSV alone ≈ 109/129 (84%), SigLIP alone ≈ 102/129 (79%).

Settings measured:
  * refset exp_current — the 43 refs of the experiment (base mockups + 4 field refs), 22 names, no brand filter;
  * refset full        — the whole production catalog index (studio variants + field + PDF cards);
  * prod               — full catalog, brand filter "AI TEA", ревень excluded (what retrieve_refs does in the graph);
reported as top-1 and recall@3 (is the truth among the 3 candidates that pass 2 will see).

    python evals/rag_sanity.py            # writes evals/results/rag_sanity_<ts>.json
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import numpy as np  # noqa: E402

from app.catalog import CANON_TO_KEY, Ref, load_catalog  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.rag.embed import get_siglip  # noqa: E402
from app.rag.index import MemoryIndex  # noqa: E402
from app.rag.retrieve import Retriever  # noqa: E402
from app.vision.crops import crop_xyxy_px, load_image  # noqa: E402

SRC = REPO / "evals" / "golden" / "silver_src"
PINK = ["персик", "малина", "клубника", "ревень", "гуава", "помело", "манго", "мандарин"]  # gate edition 20.08


def exp_current_refs(catalog: list[Ref]) -> list[Ref]:
    """Map the experiment's 'current' set (refs/NN__slug__variant.jpg + refs_field/*) onto catalog keys."""
    by_key = {r.key.lower(): r for r in catalog}
    out = []
    for r in json.loads((SRC / "refsets_24_08.json").read_text(encoding="utf-8"))["current"]:
        base = CANON_TO_KEY[r["canon"]]
        if r["source"] == "H2_field":
            key = Path(r["file"]).stem.replace("__FIELD_", "__field_").replace("_FIELD_", "_field_").lower()
            key = key.removesuffix("_1")
        else:
            key = base if r["variant"] == "base" else f"{base}__{r['variant']}"
        hit = by_key.get(key)
        if hit is None:
            print(f"  [exp_current] no catalog file for {key}")
            continue
        out.append(hit)
    return out


def load_units():
    meta = json.loads((SRC / "multi_crops_meta.json").read_text(encoding="utf-8"))
    setup = json.loads((SRC / "multi_setup.json").read_text(encoding="utf-8"))
    return [dict(o, box=meta[o["idx"]]["box"]) for o in setup["ours"] if not o["unsure"]]


def main() -> int:
    s = get_settings()
    frames_dir = s.data_dir / "frames" / "examples"
    catalog = load_catalog(str(s.catalog_path))
    if not catalog:
        print("!! no catalog.jsonl — run `make catalog` first")
        return 2
    units = load_units()
    images = {}
    crops = []
    for u in units:
        if u["photo"] not in images:
            images[u["photo"]] = load_image(frames_dir / f"{u['photo']}.JPG")
        crops.append(crop_xyxy_px(images[u["photo"]], u["box"]))
    print(f"units: {len(units)} strict from {len(images)} frames")

    siglip = get_siglip()
    if siglip is not None:  # embed each crop once, reuse across the settings below
        cache: dict[int, np.ndarray] = {}
        raw_batch = siglip.batch

        def cached_batch(xs, bs=16):
            todo = [x for x in xs if id(x) not in cache]
            if todo:
                for x, v in zip(todo, raw_batch(todo, bs), strict=True):
                    cache[id(x)] = v
            return np.stack([cache[id(x)] for x in xs])

        siglip.batch = cached_batch
    cat_dir = Path(s.catalog_path).parent
    snap = cat_dir / "index.npz"
    full = MemoryIndex.load(snap) if snap.exists() else None
    if full is None:
        print("!! no index.npz — run `make index`")
        return 2

    def sub_index(refs: list[Ref]) -> MemoryIndex:
        keys = [r.key for r in refs]
        pos = {r.key: i for i, r in enumerate(full.refs)}
        m = MemoryIndex()
        idx = [pos[k] for k in keys]
        m.upsert([full.refs[i] for i in idx], full.sig[idx] if full.sig is not None else None, full.hsv[idx])
        return m

    exp_refs = exp_current_refs(catalog)
    settings = [
        ("exp_current / siglip+hsv", sub_index(exp_refs), True, None, None),
        ("exp_current / hsv", sub_index(exp_refs), False, None, None),
        ("full / siglip+hsv", full, True, None, None),
        ("prod: full, brand filter, no ревень", full, True, "AI TEA", ["aitea_reven"]),
    ]
    if siglip is None:
        settings = [x for x in settings if not x[2]]
        print("!! SigLIP ONNX not found — HSV only")

    results, per_frame = {}, defaultdict(dict)
    t0 = time.time()
    for name, idx, use_sig, brand, excl in settings:
        retr = Retriever(idx, siglip if use_sig else None, stage1_limit=10_000)
        top1 = rec3 = pink_ok = pink_n = 0
        errs = Counter()
        by_frame = defaultdict(lambda: [0, 0])
        for u, crop in zip(units, crops, strict=True):
            r = retr.retrieve([crop], brand=brand, k=3, exclude_keys=excl)
            names = [c.canon_name for c in r.candidates]
            ok = bool(names) and names[0] == u["gt"]
            top1 += ok
            rec3 += u["gt"] in names
            by_frame[u["photo"]][0] += ok
            by_frame[u["photo"]][1] += 1
            if any(p in u["gt"].lower() for p in PINK):
                pink_n += 1
                pink_ok += ok
            if not ok:
                errs[(u["gt"].replace("AI TEA ", ""), (names[0] if names else "—").replace("AI TEA ", ""))] += 1
        n = len(units)
        results[name] = {"top1": top1, "n": n, "top1_acc": round(top1 / n, 4), "recall_at_3": round(rec3 / n, 4),
                         "pink_acc": round(pink_ok / max(1, pink_n), 4), "pink_n": pink_n, "refs": idx.count(),
                         "top_errors": [f"{a} → {b} ×{c}" for (a, b), c in errs.most_common(6)]}
        for f, (a, b) in by_frame.items():
            per_frame[f][name] = f"{a}/{b}"
        print(f"{name:40s} top-1 {top1}/{n} ({top1 / n:.0%})  recall@3 {rec3 / n:.0%}  pink {pink_ok}/{pink_n}  refs {idx.count()}")
    print(f"done in {time.time() - t0:.0f}s")

    main_key = "exp_current / siglip+hsv" if siglip else "exp_current / hsv"
    out = {
        "name": "rag_sanity",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "offline",
        "config": {"units": len(units), "frames": sorted(images), "siglip": bool(siglip), "catalog_refs": len(catalog)},
        "summary": {"subtype_acc": results[main_key]["top1_acc"], "subtype_acc_pink": results[main_key]["pink_acc"],
                    "recall_at_3": results[main_key]["recall_at_3"], "n_units": len(units), "n_frames": len(images)},
        "slices": {k: {"top1_acc": v["top1_acc"], "recall_at_3": v["recall_at_3"], "pink_acc": v["pink_acc"], "refs": v["refs"]}
                   for k, v in results.items()},
        "per_frame": [{"frame_id": f, "tier": "silver", **v} for f, v in sorted(per_frame.items())],
        "details": results,
        "notes": "Reference (24.08, embedding_experiment/REPORT.md): ensemble 120/129 (93%), HSV 109/129 (84%), SigLIP 102/129 (79%).",
    }
    res_dir = REPO / "evals" / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    p = res_dir / f"rag_sanity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
