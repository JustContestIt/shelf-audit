#!/usr/bin/env python3
"""Fetch the SigLIP vision tower (ONNX) used by the visual RAG.

Weights are not stored in git (372 MB). Two ways to get them:

1. From Hugging Face (default). The ONNX export of google/siglip-base-patch16-224
   published by Xenova for transformers.js:
       python data/scripts/fetch_models.py
2. From a local folder that already has the file (e.g. the old models_onnx/):
       python data/scripts/fetch_models.py --from-dir "C:/Users/<me>/Desktop/Work/Artyom/models_onnx"

Result: data/models/siglip_vision.onnx (+ .sha256). Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
TARGET = "siglip_vision.onnx"
HF_URL = "https://huggingface.co/Xenova/siglip-base-patch16-224/resolve/main/onnx/vision_model.onnx"
LOCAL_CANDIDATES = ("siglip_vision.onnx", "vision_model.onnx")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-dir", help="copy from a local folder instead of downloading")
    ap.add_argument("--url", default=HF_URL)
    args = ap.parse_args(argv)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dst = MODELS_DIR / TARGET
    if dst.exists() and dst.stat().st_size > 100_000_000:
        print(f"already present: {dst} ({dst.stat().st_size / 1e6:.0f} MB)")
    elif args.from_dir:
        src_dir = Path(args.from_dir).expanduser()
        src = next((src_dir / n for n in LOCAL_CANDIDATES if (src_dir / n).exists()), None)
        if src is None:
            print(f"!! none of {LOCAL_CANDIDATES} in {src_dir}", file=sys.stderr)
            return 2
        shutil.copyfile(src, dst)
        print(f"copied {src} -> {dst}")
    else:
        print(f"downloading {args.url}")
        tmp = dst.with_suffix(".part")
        with urllib.request.urlopen(args.url) as r, tmp.open("wb") as f:  # noqa: S310 (fixed https URL)
            shutil.copyfileobj(r, f, length=1 << 20)
        tmp.replace(dst)
    digest = sha256(dst)
    (MODELS_DIR / (TARGET + ".sha256")).write_text(digest + "\n")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
