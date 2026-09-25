"""Embed every reference image of data/catalog/catalog.jsonl and load them into the vector store.

    python -m app.rag.build_index              # pgvector if DATABASE_URL is set, plus data/catalog/index.npz
    python -m app.rag.build_index --no-db      # only the .npz snapshot (offline / CI / no Postgres)
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from app.catalog import load_catalog
from app.config import get_settings
from app.rag.embed import get_siglip, hsv_feat
from app.rag.index import MemoryIndex, PgVectorIndex


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--catalog", type=Path, default=s.catalog_path)
    a = ap.parse_args(argv)

    refs = load_catalog(str(a.catalog))
    if not refs:
        print(f"!! empty catalog {a.catalog} — run `python -m app.rag.ingest` first")
        return 2
    cat_dir = Path(a.catalog).parent
    siglip = get_siglip()
    t0 = time.time()
    paths = [cat_dir / r.path for r in refs]
    hsv = np.stack([hsv_feat(p) for p in paths])
    sig = siglip.batch([str(p) for p in paths]) if siglip else None
    print(f"embedded {len(refs)} refs in {time.time() - t0:.1f}s ({'SigLIP + HSV' if siglip else 'HSV only: no ONNX model'})")

    mem = MemoryIndex()
    mem.upsert(refs, sig, hsv)
    snap = cat_dir / "index.npz"
    mem.save(snap)
    print(f"snapshot -> {snap}")
    if s.database_url and not a.no_db:
        idx = PgVectorIndex(s.database_url)
        idx.upsert(refs, sig, hsv)
        print(f"pgvector: {idx.count()} rows in ref_embeddings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
