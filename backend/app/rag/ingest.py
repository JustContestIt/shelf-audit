"""Build data/catalog/catalog.jsonl from the customer's PDF catalog and reference folders.

Sources (all under data/catalog/, not in git):
  * pdf/brands_catalog_new_2.pdf — «Справочник брендов», 5 pages exported from Figma:
    one product image per SKU + caption with the canon name. The export has a broken
    ToUnicode map: lowercase Cyrillic comes out shifted by -0x400 ('а' -> '0'), uppercase
    0x411..0x41F lands in PDFDocEncoding accents ('˚' = 'О') or is lost. We decode what can be
    decoded and fuzzy-match the caption to the 22 known canon names (app.catalog.SKUS).
  * refs_1280/*.jpg — studio mockups + variants (grammar: <key>__<pack>_<lang|rot>).
  * field_refs/* — field crops from real shelves (the strongest refs, see REPORT 24.08).

Chunking: one catalog row = one SKU card image (not fixed-size text chunks): a card is
"image + caption", which is the unit the retriever needs to return.

    python -m app.rag.ingest            # writes catalog.jsonl + pdf_cards/*.png, prints a check table
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from pathlib import Path

from app.catalog import SKUS, Ref, base_key, parse_ref_name
from app.config import get_settings

# brands_catalog_new_2.pdf is the current 5-page catalog; Frame 29–33 are its pages exported one by one
# (Frame 30 = an older AI TEA page with different mockups). brands_catalog_new.pdf is the old 1-page version.
PDF_NAMES = ["brands_catalog_new_2.pdf", "Frame 29.pdf", "Frame 30.pdf", "Frame 31.pdf", "Frame 32.pdf", "Frame 33.pdf"]
ACCENTS = {"˘": 0x18, "ˇ": 0x19, "ˆ": 0x1A, "˙": 0x1B, "˝": 0x1C, "˛": 0x1D, "˚": 0x1E, "˜": 0x1F}
GARBLED_MARK = re.compile(r"[0-9:;<=>?@" + "".join(ACCENTS) + "]")


def decode_figma(word: str) -> str:
    """Undo the -0x400 shift of Figma's broken ToUnicode map for one word.
    Latin words ('AI', 'TEA', 'Chino', 'Bellini') have none of the marker chars and are kept."""
    if not GARBLED_MARK.search(word):
        return word
    out = []
    for ch in word:
        o = ord(ch)
        if 0x30 <= o <= 0x4F:
            out.append(chr(o + 0x400))            # а..я
        elif ch in ACCENTS:
            out.append(chr(ACCENTS[ch] + 0x400))  # И..П
        else:
            out.append(ch)
    return "".join(out)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("ё", "е")).strip()


def match_canon(caption: str, brand_hint: str | None = None) -> tuple[str | None, float]:
    """Best canon name for a decoded caption. Lost capitals ('уратино') are tolerated by fuzzy match."""
    cands = [(k, v[1]) for k, v in SKUS.items() if brand_hint is None or v[0] == brand_hint]
    best, score = None, 0.0
    cap = _norm(caption)
    for _, canon in cands:
        r = difflib.SequenceMatcher(None, cap, _norm(canon)).ratio()
        if r > score:
            best, score = canon, r
    return best, score


PAGE_BRANDS = [("уратино", "Буратино"), ("ai tea", "AI TEA"), ("tamga", "Tamga"), ("chino", "Chino"), ("омпотай", "Компотай")]


def parse_pdf(pdf_path: Path, out_dir: Path) -> list[dict]:
    import pymupdf

    doc = pymupdf.open(pdf_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for pno, page in enumerate(doc):
        # spans, not words: Figma puts the 2nd caption line into the same span after "\n" with
        # zero-width glyph boxes, and word extraction silently drops those glyphs
        spans = []
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for sp in line["spans"]:
                    if sp["text"].strip():
                        spans.append((sp["bbox"], sp["text"]))
        page_text = _norm(" ".join(decode_figma(w) for _, t in spans for w in t.split()))
        brand_hint = next((b for token, b in PAGE_BRANDS if token in page_text[:60]), None)
        infos = page.get_image_info(xrefs=True)
        for n, info in enumerate(sorted(infos, key=lambda i: (round(i["bbox"][1] / 50), i["bbox"][0]))):
            x0, y0, x1, y1 = info["bbox"]
            cap = [(bb, t) for bb, t in spans if x0 - 5 <= (bb[0] + bb[2]) / 2 <= x1 + 5 and y1 - 5 <= bb[1] <= y1 + 160]
            cap.sort(key=lambda it: (round(it[0][1] / 20), it[0][0]))
            caption_raw = " ".join(t.replace("\n", " ") for _, t in cap)
            caption = " ".join(decode_figma(w) for w in caption_raw.split())
            canon, score = match_canon(caption, brand_hint)
            if brand_hint == "Tamga" and not caption.strip():
                canon, score = "Tamga", 1.0
            key = next((k for k, v in SKUS.items() if v[1] == canon), None)
            img = doc.extract_image(info["xref"])
            sha = hashlib.sha1(img["image"]).hexdigest()[:10]
            fname = f"{key or f'p{pno}_{n}'}__pdf_{sha}.{img['ext']}"
            (out_dir / fname).write_bytes(img["image"])
            cards.append({"page": pno, "bbox": [round(v) for v in info["bbox"]], "caption_raw": caption_raw,
                          "caption": caption, "canon_name": canon if score >= 0.6 else None, "match": round(score, 3),
                          "key": key if score >= 0.6 else None, "file": fname, "brand_hint": brand_hint,
                          "sha": sha, "pdf": pdf_path.name})
    return cards


def scan_folder(folder: Path, rel_root: Path) -> list[Ref]:
    refs = []
    for p in sorted(folder.glob("*")):
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        info = parse_ref_name(p.stem)
        if info["base"] not in SKUS:
            continue
        brand, canon, _ = SKUS[info["base"]]
        refs.append(Ref(key=info["key"], brand=brand, canon_name=canon, variant=info["variant"], pack=info["pack"],
                        lang=info["lang"], source=info["source"], path=str(p.relative_to(rel_root)).replace("\\", "/"),
                        mime_type="image/png" if p.suffix.lower() == ".png" else "image/jpeg"))
    return refs


def build_catalog(catalog_dir: Path) -> tuple[list[Ref], dict]:
    report: dict = {"pdf": [], "folders": {}, "missing_skus": [], "xlsx_check": None}
    refs: list[Ref] = []
    seen_sha: set[str] = set()
    for name in PDF_NAMES:
        pdf = catalog_dir / "pdf" / name
        if not pdf.exists():
            continue
        for c in parse_pdf(pdf, catalog_dir / "pdf_cards"):
            dup = c["sha"] in seen_sha
            seen_sha.add(c["sha"])
            report["pdf"].append({**c, "duplicate": dup})
            if c["key"] and not dup:
                brand, canon, _ = SKUS[c["key"]]
                refs.append(Ref(key=f"{c['key']}__pdf_{c['sha']}", brand=brand, canon_name=canon, variant="pdf", source="pdf",
                                path="pdf_cards/" + c["file"], mime_type="image/png" if c["file"].endswith(".png") else "image/jpeg",
                                extra={"caption": c["caption"], "match": c["match"], "pdf": c["pdf"], "page": c["page"]}))
    for sub in ("refs_1280", "field_refs"):
        folder = catalog_dir / sub
        if folder.exists():
            found = scan_folder(folder, catalog_dir)
            report["folders"][sub] = len(found)
            refs += found
    have = {base_key(r.key) for r in refs}
    report["missing_skus"] = sorted(set(SKUS) - have)

    xlsx = catalog_dir / "brand_catalog_before_31_08.xlsx"
    if xlsx.exists():
        import openpyxl

        ws = openpyxl.load_workbook(xlsx, read_only=True).active
        keys = [r[0] for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0]]
        ours = {r.key.lower() for r in refs}
        report["xlsx_check"] = {"rows": len(keys), "without_file": [k for k in keys if k.lower() not in ours]}
    return refs, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog-dir", type=Path, default=get_settings().data_dir / "catalog")
    a = ap.parse_args(argv)
    refs, report = build_catalog(a.catalog_dir)
    out = a.catalog_dir / "catalog.jsonl"
    out.write_text("".join(json.dumps(r.to_json(), ensure_ascii=False) + "\n" for r in refs), encoding="utf-8")
    (a.catalog_dir / "ingest_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"catalog: {len(refs)} refs -> {out}")
    print("PDF cards:")
    for c in report["pdf"]:
        if not c["duplicate"]:
            print(f"  {c['pdf'][:14]:14s} p{c['page']} {c['caption_raw'][:26]:26s} -> {c['caption'][:28]:28s} => {c['canon_name']} ({c['match']})")
    print(f"  ({sum(c['duplicate'] for c in report['pdf'])} duplicate images across PDFs skipped)")
    print("folders:", report["folders"], "| SKUs without any ref:", report["missing_skus"] or "none")
    if report["xlsx_check"]:
        print(f"n8n brand_catalog rows: {report['xlsx_check']['rows']}, without a local file: "
              f"{report['xlsx_check']['without_file'] or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
