#!/usr/bin/env python3
"""Convert every existing ground truth of the project into ONE golden format (evals/golden/<frame>.json).

Unit of an example = a shelf (frame x shelf): left-to-right sequence of front-row units
(our SKUs and foreign ones) -> count GT = number of our units, positional subtype GT, pack GT.

Sources:
  gold   IMG_0644 (== AITEA_5SHELF): bench/GT_aitea_5shelf.json (positions + 5 foreign) + model_compare/gt_IMG_0644.json (packs)
  gold   IMG_0643: openai_harness/gt_IMG_0643_66.json (groups, field recount 04.08)
  draft  COMP-1:   gt_COMP1_draft.md (frame file is missing — kept out of runs until found)
  silver IMG_0614/0646/0648/0649/0650: embedding_experiment labels_IMG_*.json + YOLO rows (visual labels by zooms, ±1–2)
  silver IMG_0645: labelled 25.09 by zooms (Буратино stand, packs 1 / 1.5 / 2 L — the format_geo case)
  (field_refs_31_08_2026/ are single-product close-ups for reference images, not shelves — no GT from there)

    python evals/tools/build_golden.py --artyom "C:/.../Artyom"
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "evals" / "golden"
SRC = GOLDEN / "silver_src"
FOREIGN = "ЧУЖОЙ"
SHORT = {"помело": "AI TEA помело-цветок апельсина", "манго": "AI TEA манго-маракуйя", "клубника": "AI TEA клубника-киви",
         "лимон": "AI TEA лимон-лайм-жасмин", "малина": "AI TEA малина", "персик": "AI TEA персик-жасмин",
         "мандарин": "AI TEA мандарин-лаванда", "гуава": "AI TEA гуава-тропики", "ревень": "AI TEA ревень"}
PINK = ("персик", "малина", "клубника", "ревень", "гуава", "помело")


def unit(brand, subtype=None, fmt=None, **tags):
    u = {"brand": brand, "subtype": subtype, "format": fmt}
    u.update({k: v for k, v in tags.items() if v})
    return u


def shelf_tags(units):
    tags = []
    if any(u["brand"] == FOREIGN for u in units):
        tags.append("foreign_nearby")
    if any(u.get("subtype") and any(p in u["subtype"] for p in PINK) for u in units):
        tags.append("pink_zone")
    fm = {u.get("format") for u in units if u["brand"] != FOREIGN and u.get("format")}
    if len(fm) > 1:
        tags.append("mixed_packs")
    if any(u.get("unsure") for u in units):
        tags.append("unsure_labels")
    return tags


def finish(frame: dict) -> dict:
    for s in frame["shelves"]:
        s["units_gt"] = sum(1 for u in s["units"] if u["brand"] != FOREIGN)
        s["tags"] = sorted(set(s.get("tags", [])) | set(shelf_tags(s["units"])))
    frame["units_gt"] = sum(s["units_gt"] for s in frame["shelves"])
    frame["foreign_gt"] = sum(1 for s in frame["shelves"] for u in s["units"] if u["brand"] == FOREIGN)
    return frame


def img_0644(artyom: Path) -> dict:
    g5 = json.loads((artyom / "bench" / "GT_aitea_5shelf.json").read_text(encoding="utf-8"))
    g44 = json.loads((artyom / "model_compare" / "gt_IMG_0644.json").read_text(encoding="utf-8"))
    packs = {}
    for u in g44["units"]:
        packs.setdefault(u["shelf"], u["format"])
    shelves = []
    for s in range(1, 6):
        units = [unit(FOREIGN) if x == FOREIGN else unit("AI TEA", g5["aliases"][x], packs[s]) for x in g5["shelves"][str(s)]]
        shelves.append({"shelf_index": s, "units": units})
    return finish({
        "frame_id": "IMG_0644", "aliases": ["AITEA_5SHELF"], "tier": "gold", "file": "frames/examples/IMG_0644.JPG",
        "size": [g44["width"], g44["height"]], "variants": ["orig", "tg1280"],
        "source": "bench/GT_aitea_5shelf.json (positions, foreign) + model_compare/gt_IMG_0644.json (packs)",
        "notes": "AITEA_5SHELF of the 31.08–01.09 series is this frame: identical shelf composition and identical "
                 "pass-1 boxes at temperature 0. Shelf counts 11/11/11/10/10 = field recount; positions checked on crops 31.08.",
        "shelves": shelves,
    })


def img_0643(artyom: Path) -> dict:
    g = json.loads((artyom / "openai_harness" / "gt_IMG_0643_66.json").read_text(encoding="utf-8"))
    shelves = []
    for s in g["shelves"]:
        units = []
        for grp in s["groups"]:
            units += [unit(grp["brand"], grp["subtype"], grp["format"], gt_unverified=grp.get("verify", False))] * grp["n"]
        shelves.append({"shelf_index": s["shelf_index"], "units": [dict(u) for u in units]})
    return finish({
        "frame_id": "IMG_0643", "aliases": [], "tier": "gold", "file": "frames/examples/IMG_0643.JPG", "size": [4032, 3024],
        "variants": ["orig", "tg1280"], "source": "openai_harness/gt_IMG_0643_66.json",
        "notes": g["comment"] + " Order inside a shelf = group order left to right.",
        "shelves": shelves,
    })


def comp1() -> dict:
    mk = lambda seq, fmt: [unit("AI TEA", SHORT[n], fmt) for n in seq]  # noqa: E731
    s1 = [unit(FOREIGN)] + mk(["помело"] * 2 + ["манго"] + ["клубника"] * 2 + ["лимон"] * 2 + ["малина"] * 2 + ["персик"] * 2 + ["мандарин"], "банка 0,45 л")
    s2 = [unit(FOREIGN)] * 2 + mk(["помело"] * 2 + ["манго"] + ["клубника"] + ["лимон"] * 2 + ["малина"] * 2 + ["персик"] * 2 + ["мандарин"], "банка 0,45 л")
    s3 = mk(["малина"] * 2 + ["персик"] * 3 + ["манго"] * 3 + ["клубника"] * 3, "ПЭТ 0,5 л")
    s45 = mk(["малина"] * 2 + ["персик"] + ["лимон"] * 2 + ["помело"] + ["манго"] * 2 + ["клубника"] * 2, "ПЭТ 1 л")
    return finish({
        "frame_id": "COMP-1", "aliases": [], "tier": "draft", "file": None, "size": [1920, 2560], "variants": ["orig"],
        "source": "gt_COMP1_draft.md (20.08)",
        "notes": "Frame file is not in the folder — get it from Telegram / Artyom. ⚠ items of the draft are unconfirmed "
                 "(white can on shelf 1, second purple can on shelf 2). Order inside shelves 4–5 is by the draft list, not by position.",
        "shelves": [{"shelf_index": i + 1, "units": [dict(u) for u in s], "tags": ["draft_order"] if i >= 3 else []}
                    for i, s in enumerate([s1, s2, s3, s45, s45])],
    })


def img_0645() -> dict:
    """Labelled 25.09 by zooming into each shelf (same protocol as the 24.08 silver labels). Packs read from the
    labels where printed (1L / 1.5L / 2L); shelf 1 pack not readable -> null. Shelf 5 = shrink-wrapped 2-packs
    of 2 L (-25% promo): multipacks are out of the counting rules, so the shelf is ignored."""
    klass, dm = "Буратино классический", "Буратино дыня-мята"
    s1 = [unit("Буратино", klass, None, unsure=True)] + [unit("Буратино", klass, None) for _ in range(12)]
    s2 = [unit("Буратино", klass, "ПЭТ 1 л") for _ in range(6)] + [unit("Буратино", dm, "ПЭТ 1 л") for _ in range(4)]
    s3 = [unit("Буратино", klass, "ПЭТ 1,5 л") for _ in range(9)]
    s4 = [unit("Буратино", klass, "ПЭТ 2 л") for _ in range(8)]
    return finish({
        "frame_id": "IMG_0645", "aliases": [], "tier": "silver", "file": "frames/examples/IMG_0645.JPG", "size": [3024, 4032],
        "variants": ["orig", "tg1280"], "source": "labels by zooms 25.09.2026 (Claude), to be confirmed by Nikita",
        "notes": "Буратино stand, competitors (Tassay, Zigi-Zagi, Holiday, Alasu, Fanta) are clearly different products and "
                 "are not part of the GT (the prompt does not box them). Shelf 1: the leftmost bottle is turned sideways "
                 "(unsure). Shelf 5 (multipacks) is ignored.",
        "ignore_shelves": [5],
        "shelves": [{"shelf_index": i + 1, "units": u, "tags": ["pack_geo"] if i > 0 else []} for i, u in enumerate([s1, s2, s3, s4])],
    })


def silver() -> list[dict]:
    meta = json.loads((SRC / "multi_crops_meta.json").read_text(encoding="utf-8"))
    labels = {}
    for f in sorted(SRC.glob("labels_IMG_*.json")):
        labels.update(json.loads(f.read_text(encoding="utf-8")))
    rows: dict = defaultdict(lambda: defaultdict(list))
    for k, v in labels.items():
        m = meta[int(k)]
        if v == "J":  # fragments / back rows: out of the metrics by definition of the task
            continue
        rows[m["photo"]][m["row"]].append((m["box"][0], v, m["box"]))
    sizes = {"IMG_0614": [960, 1280], "IMG_0646": [3024, 4032], "IMG_0648": [4032, 3024], "IMG_0649": [3024, 4032],
             "IMG_0650": [4032, 3024]}
    out = []
    for photo in sorted(rows):
        if photo == "IMG_0644":  # gold exists
            continue
        shelves = []
        for r in sorted(rows[photo]):
            items = sorted(rows[photo][r])
            if not any(v != "F" for _, v, _ in items):
                continue  # rows of competitors only are not shelves of the task
            units = []
            for _, v, box in items:
                if v == "F":
                    units.append(unit(FOREIGN, box_px=box))
                else:
                    units.append(unit("AI TEA", "AI TEA " + v.rstrip("?"), None, unsure=v.endswith("?"), box_px=box))
            shelves.append({"shelf_index": len(shelves) + 1, "yolo_row": r, "units": units})
        out.append(finish({
            "frame_id": photo, "aliases": [], "tier": "silver", "file": f"frames/examples/{photo}.JPG", "size": sizes[photo],
            "variants": ["orig"] if photo == "IMG_0614" else ["orig", "tg1280"],
            "source": "embedding_experiment 24.08: labels_IMG_*.json + multi_crops_meta.json (YOLO11x rows)",
            "notes": "Visual labels by zooms (not a field recount), ±1–2 units; packs not labelled; shelf numbers are "
                     "YOLO rows with our units, top to bottom — the model may number shelves differently (scored by order).",
            "shelves": shelves,
        }))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artyom", required=True, type=Path)
    a = ap.parse_args()
    frames = [img_0644(a.artyom), img_0643(a.artyom), comp1(), img_0645(), *silver()]
    index = []
    for f in frames:
        (GOLDEN / f"{f['frame_id']}.json").write_text(json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({"frame_id": f["frame_id"], "tier": f["tier"], "shelves": len(f["shelves"]), "units_gt": f["units_gt"],
                      "foreign_gt": f["foreign_gt"], "has_file": bool(f["file"]), "variants": f["variants"]})
    (GOLDEN / "INDEX.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    runnable = [i for i in index if i["has_file"]]
    print(f"{'frame':10s} {'tier':7s} shelves units foreign")
    for i in index:
        print(f"{i['frame_id']:10s} {i['tier']:7s} {i['shelves']:7d} {i['units_gt']:5d} {i['foreign_gt']:7d}  {'' if i['has_file'] else '(no frame file)'}")
    print(f"shelf examples with a frame: {sum(i['shelves'] for i in runnable)} "
          f"(x variants: {sum(i['shelves'] * len(i['variants']) for i in runnable)}); with drafts: {sum(i['shelves'] for i in index)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
