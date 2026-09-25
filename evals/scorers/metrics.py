"""Metrics of one run (frame x variant x repeat) and their aggregation."""
from __future__ import annotations

import statistics
from collections import defaultdict

from evals.scorers.align import FOREIGN, align_shelf

PINK = ("персик", "малина", "клубника", "ревень", "гуава", "помело")


def _short(s: str | None) -> str:
    return (s or "—").replace("AI TEA ", "").replace("Буратино ", "Б. ").replace("Компотай ", "К. ")


def shelf_map(pred_boxes: list[dict], gt: dict) -> dict[int, int]:
    """pred shelf -> GT shelf. Gold frames: by index. Silver frames (YOLO rows): by rank of shelves with our units."""
    pred_shelves = sorted({b.get("shelf_index") for b in pred_boxes if b.get("label") not in (None, FOREIGN)} - {None})
    gt_shelves = [s["shelf_index"] for s in gt["shelves"]]
    if gt.get("tier") == "silver" and gt.get("shelf_match", "rank") == "rank" and gt["frame_id"] != "IMG_0645":
        return dict(zip(pred_shelves, gt_shelves, strict=False))
    return {s: s for s in pred_shelves}


def score_frame(pred_boxes: list[dict], gt: dict) -> dict:
    ignore = set(gt.get("ignore_shelves") or [])
    pred_boxes = [b for b in pred_boxes if b.get("shelf_index") not in ignore]
    m = shelf_map(pred_boxes, gt)
    by_shelf: dict[int, list[dict]] = defaultdict(list)
    unmapped = 0
    for b in pred_boxes:
        s = m.get(b.get("shelf_index"))
        if s is None:
            unmapped += b.get("label") not in (None, FOREIGN)
            continue
        by_shelf[s].append(b)

    shelves = []
    tot = {"units_gt": 0, "units_pred": 0, "sub_ok": 0, "sub_n": 0, "pink_ok": 0, "pink_n": 0, "pack_ok": 0, "pack_n": 0,
           "contamination": 0, "count_exact": 0, "abs_err": 0, "unaligned": 0}
    errors = []
    for sh in gt["shelves"]:
        si = sh["shelf_index"]
        pred = by_shelf.get(si, [])
        own_gt = sh["units_gt"]
        own_pred = sum(1 for b in pred if b.get("label") not in (None, FOREIGN))
        al = align_shelf(pred, sh["units"])
        rec = {"shelf": si, "units_gt": own_gt, "units_pred": own_pred, "count_exact": own_gt == own_pred,
               "aligned": al.aligned, "target": al.target, "lost": al.lost, "extra": al.extra, "subtype_errors": 0,
               "pack_errors": 0, "contamination": 0, "tags": sh.get("tags", [])}
        tot["units_gt"] += own_gt
        tot["units_pred"] += own_pred
        tot["count_exact"] += own_gt == own_pred
        tot["abs_err"] += abs(own_gt - own_pred)
        if not al.aligned:
            tot["unaligned"] += 1
            errors.append(f"П{si}: боксов {own_pred}, в GT {own_gt} — позиции не сверить")
        for i, (p, g) in enumerate(al.pairs, 1):
            ours_p = p.get("label") not in (None, FOREIGN)
            if g["brand"] == FOREIGN:
                if ours_p:
                    rec["contamination"] += 1
                    errors.append(f"П{si}.{i}: чужая → {_short(p.get('subtype') or p.get('label'))} (в счёте!)")
                continue
            if g.get("unsure"):
                continue
            tot["sub_n"] += 1
            ok = ours_p and (p.get("subtype") or None) == (g.get("subtype") or None)
            tot["sub_ok"] += ok
            if g.get("subtype") and any(k in g["subtype"] for k in PINK):
                tot["pink_n"] += 1
                tot["pink_ok"] += ok
            if not ok:
                rec["subtype_errors"] += 1
                errors.append(f"П{si}.{i}: {_short(g.get('subtype'))} → {_short(p.get('subtype')) if ours_p else 'не наш'}")
            if g.get("format") and not g.get("gt_unverified"):
                tot["pack_n"] += 1
                pok = ours_p and p.get("format") == g["format"]
                tot["pack_ok"] += pok
                rec["pack_errors"] += not pok
        if al.lost:
            errors.append(f"П{si}: потеряно единиц {al.lost}")
        if al.extra:
            errors.append(f"П{si}: лишних боксов {al.extra}")
        tot["contamination"] += rec["contamination"]
        shelves.append(rec)
    n_sh = len(gt["shelves"])
    return {
        "shelves": n_sh, "units_gt": tot["units_gt"], "units_pred": tot["units_pred"],
        "count_exact_shelves": tot["count_exact"], "count_abs_err": tot["abs_err"],
        "subtype_errors": tot["sub_n"] - tot["sub_ok"], "subtype_scored": tot["sub_n"],
        "pink_errors": tot["pink_n"] - tot["pink_ok"], "pink_scored": tot["pink_n"],
        "pack_errors": tot["pack_n"] - tot["pack_ok"], "pack_scored": tot["pack_n"],
        "contamination": tot["contamination"], "unaligned_shelves": tot["unaligned"], "unmapped_units": unmapped,
        "per_shelf": shelves, "errors": errors,
    }


def _ratio(a, b):
    return round(a / b, 4) if b else None


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 2)


def aggregate(runs: list[dict]) -> dict:
    """runs: [{frame_id, variant, repeat, tier, score:{...}, cost_usd, latency_s, ...}] -> summary dict."""
    ok = [r for r in runs if r.get("score")]
    s = lambda k: sum(r["score"][k] for r in ok)  # noqa: E731
    by_fv: dict[tuple, list[int]] = defaultdict(list)
    for r in ok:
        by_fv[(r["frame_id"], r["variant"])].append(r["score"]["subtype_errors"])
    sigmas = [statistics.pstdev(v) for v in by_fv.values() if len(v) >= 2]
    costs = [r["cost_usd"] for r in ok if r.get("cost_usd") is not None]
    lats = [r["latency_s"] for r in ok if r.get("latency_s") is not None]
    return {
        "count_exact_shelf_rate": _ratio(s("count_exact_shelves"), s("shelves")),
        "count_mae": _ratio(s("count_abs_err"), s("shelves")),
        "subtype_acc": _ratio(s("subtype_scored") - s("subtype_errors"), s("subtype_scored")),
        "subtype_acc_pink": _ratio(s("pink_scored") - s("pink_errors"), s("pink_scored")),
        "contamination": s("contamination") if ok else None,
        "pack_acc": _ratio(s("pack_scored") - s("pack_errors"), s("pack_scored")),
        "stability_sigma_subtype_err": round(statistics.mean(sigmas), 2) if sigmas else None,
        "cost_usd_per_photo": round(statistics.mean(costs), 4) if costs else None,
        "latency_p50_s": percentile(lats, 0.5), "latency_p95_s": percentile(lats, 0.95),
        "n_runs": len(runs), "n_failed": len(runs) - len(ok), "n_frames": len({r["frame_id"] for r in ok}),
        "n_shelves": s("shelves") if ok else 0, "n_units": s("units_gt") if ok else 0,
    }


def slices(runs: list[dict]) -> dict:
    """Metrics by tier and by shelf tag (pink_zone, foreign_nearby, mixed_packs, pack_geo)."""
    out = {}
    tiers = defaultdict(list)
    for r in runs:
        if r.get("score"):
            tiers[f"tier:{r['tier']}"].append(r)
            tiers[f"variant:{r['variant']}"].append(r)
    for k, rs in tiers.items():
        a = aggregate(rs)
        out[k] = {x: a[x] for x in ("count_exact_shelf_rate", "subtype_acc", "subtype_acc_pink", "contamination", "pack_acc",
                                    "n_runs")}
    tag_tot: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # shelves, exact, subtype errors
    for r in runs:
        for sh in (r.get("score") or {}).get("per_shelf", []):
            for t in sh.get("tags", []):
                tag_tot[t][0] += 1
                tag_tot[t][1] += sh["count_exact"]
                tag_tot[t][2] += sh["subtype_errors"]
    for t, (n, ex, se) in tag_tot.items():
        out[f"tag:{t}"] = {"shelves": n, "count_exact_shelf_rate": _ratio(ex, n), "subtype_errors_per_shelf": _ratio(se, n)}
    return out
