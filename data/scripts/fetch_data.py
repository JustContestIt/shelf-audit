#!/usr/bin/env python3
"""Copy customer data (photos, reference images, PDF catalog) into ./data.

Customer data never goes to git. This script is the only way data reaches the repo
folder: it copies an explicit allow-list from the working folder (or from private
storage mounted as a folder), verifies sizes and writes data/MANIFEST.json with
sha256 so a teammate can check they have the same bytes.

Standard library only, Python >= 3.10.

    python data/scripts/fetch_data.py --source "C:/Users/<me>/Desktop/Work/Artyom"
    python data/scripts/fetch_data.py --source /mnt/artyom --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1]

# (source relative to --source, destination relative to data/)
# Directories are copied recursively. Anything not listed here is NOT copied.
MANIFEST: list[tuple[str, str]] = [
    # --- catalog: PDF "Справочник брендов" + Figma frames ---
    ("Caspian project/brands_catalog_new_2.pdf", "catalog/pdf/brands_catalog_new_2.pdf"),
    ("Caspian project/brands_catalog_new.pdf", "catalog/pdf/brands_catalog_new.pdf"),
    ("Caspian project/Frame 29.pdf", "catalog/pdf/Frame 29.pdf"),
    ("Caspian project/Frame 30.pdf", "catalog/pdf/Frame 30.pdf"),
    ("Caspian project/Frame 31.pdf", "catalog/pdf/Frame 31.pdf"),
    ("Caspian project/Frame 32.pdf", "catalog/pdf/Frame 32.pdf"),
    ("Caspian project/Frame 33.pdf", "catalog/pdf/Frame 33.pdf"),
    # --- catalog: reference images ---
    ("Caspian project/Brands", "catalog/brands"),              # raw studio mockups by brand
    ("Vision_Assistance_upload_1280", "catalog/refs_1280"),    # 150 refs, 1280px (refs/ is a byte-identical duplicate)
    ("H2_field_refs", "catalog/field_refs"),                   # 7 field crops (cans 0.45 / PET)
    ("bench/brand_catalog_before_31_08.xlsx", "catalog/brand_catalog_before_31_08.xlsx"),
    # --- frames for golden set and demo ---
    ("Caspian project/Examples", "frames/examples"),           # IMG_0614..0650, iPhone originals
    ("field_refs_31_08_2026", "frames/field_refs_31_08_2026"), # 28 single-product field photos + 4 can crops (source of field refs)
]

# Never copied, even if someone adds a parent directory to MANIFEST.
DENY_PARTS = {
    "_to_delete", "archive", "models_onnx", "Vision_Assistance_upload_ALL", "refs",
    "openai_key.txt", "openrouter_key.txt",
}
DENY_SUFFIXES = {".env"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_files(src: Path):
    if src.is_file():
        yield src, Path()
        return
    for p in sorted(src.rglob("*")):
        if p.is_file():
            yield p, p.relative_to(src)


def denied(rel: Path) -> bool:
    return any(part in DENY_PARTS for part in rel.parts) or rel.suffix in DENY_SUFFIXES or rel.name.startswith(".~lock")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="root of the working folder (the one with 'Caspian project/')")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-hash", action="store_true", help="skip sha256 (faster on slow disks)")
    args = ap.parse_args(argv)

    source = Path(args.source).expanduser().resolve()
    if not (source / "Caspian project").exists():
        print(f"!! {source} does not look like the working folder (no 'Caspian project/')", file=sys.stderr)
        return 2

    entries, missing, total = [], [], 0
    for src_rel, dst_rel in MANIFEST:
        src = source / src_rel
        if not src.exists():
            missing.append(src_rel)
            continue
        for f, sub in iter_files(src):
            rel_to_source = f.relative_to(source)
            if denied(rel_to_source):
                continue
            dst = DATA_DIR / dst_rel / sub if sub != Path() else DATA_DIR / dst_rel
            size = f.stat().st_size
            total += size
            if not args.dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists() or dst.stat().st_size != size:
                    shutil.copyfile(f, dst)  # copyfile breaks hard links on purpose
            entries.append({
                "dst": str(dst.relative_to(DATA_DIR)).replace("\\", "/"),
                "src": str(rel_to_source).replace("\\", "/"),
                "bytes": size,
                **({} if args.no_hash or args.dry_run else {"sha256": sha256(dst)}),
            })

    print(f"{'would copy' if args.dry_run else 'copied'}: {len(entries)} files, {total / 1e6:.1f} MB")
    for m in missing:
        print(f"  missing in source: {m}")
    if not args.dry_run:
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_root_name": source.name,
            "files": entries,
            "missing": missing,
        }
        (DATA_DIR / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"manifest: {DATA_DIR / 'MANIFEST.json'}")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
