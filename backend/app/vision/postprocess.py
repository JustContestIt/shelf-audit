"""Post-processing of Gemini detections — a line-by-line port of the n8n Code nodes.

Sources (legacy/n8n, WF-2 v4.3 "noreven"):
  * «Парсинг обработки Google Vision» v7.5-format-geo  -> parse_detect_response + postprocess_detect
  * «Сборка запроса Pro» v9 (grouping part)            -> plan_groups
  * «Слияние подвидов» v9-groups                        -> merge_verify

Behaviour must stay identical to the JS (see tests/test_js_parity.py, which runs the
original JS in Node on the same inputs, including randomized boxes). The only additions
are opt-in keyword arguments that default to the n8n behaviour:
  * GeoParams — thresholds are parameters, defaults = live node (1.25 / 1.43);
  * merge_verify(targets=...) — restrict pass-2 renames to uncertain groups (ADR-007).

Coordinates: box_2d = [y_min, x_min, y_max, x_max], normalised 0..1000 (Gemini convention).
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

BRANDS: tuple[str, ...] = ("Буратино", "AI TEA", "Chino", "Компотай", "Tamga")
FOREIGN = "ЧУЖОЙ"
UNKNOWN = "НЕ ОПРЕДЕЛЁН"
CAN_045 = "банка 0,45 л"

# pass-2 gate (pass2_gate_latency_BUILD.md §1): null subtype or a "pink zone" name in pass-1 output
PINK_RE = re.compile(r"персик|малина|клубника|ревень|гуава|помело", re.IGNORECASE)

Box = dict[str, Any]


# ---------------------------------------------------------------- JS helpers
def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v: Any) -> bool:
    """JS Number.isInteger: 3 and 3.0 are integers, True is not a number."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()


def shelf_of(b: Box) -> int:
    s = b.get("shelf_index")
    return int(s) if _is_int(s) and s > 0 else 0


def _width(b: Box) -> float:
    return b["box_2d"][3] - b["box_2d"][1]


def _upper_median(xs: Iterable[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2]


def _to_fixed(x: float, n: int) -> float:
    """+x.toFixed(n): V8 rounds the exact binary value half-up (1.005.toFixed(2) == "1.00")."""
    return float(Decimal(x).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def _num(x: float) -> int | float:
    """JS numbers have no int/float split; keep ints as ints when exact (matters for JSON parity)."""
    return int(x) if isinstance(x, float) and x.is_integer() else x


def _conf_or_zero(b: Box) -> float:
    c = b.get("confidence")
    return c if _is_num(c) else 0  # JS: b.confidence ?? 0 (non-numbers compare as equal there)


# ---------------------------------------------------------------- response parsing
class DetectResponseError(ValueError):
    pass


def extract_text_json(raw: dict) -> tuple[dict, str | None]:
    """Last text part of candidates[0] parsed as JSON; also returns finishReason."""
    cand = (raw.get("candidates") or [None])[0] or {}
    parts = (cand.get("content") or {}).get("parts") or []
    text = next((p["text"] for p in reversed(parts) if isinstance(p.get("text"), str)), None)
    if text is None:
        raise DetectResponseError("Нет текстового ответа Gemini: " + json.dumps(raw, ensure_ascii=False)[:800])
    return json.loads(text), cand.get("finishReason")


def usage_of(raw: dict) -> dict:
    u = raw.get("usageMetadata") or {}
    return {
        "prompt_tokens": u.get("promptTokenCount"),
        "cached_tokens": u.get("cachedContentTokenCount"),
        "output_tokens": u.get("candidatesTokenCount"),
        "thoughts_tokens": u.get("thoughtsTokenCount"),
    }


# ---------------------------------------------------------------- pass 1
@dataclass(frozen=True)
class GeoParams:
    """format_geo thresholds. Defaults = live WF-2 v4.3 node (01.09).
    The 10.08 BUILD file had 1.30/1.48 — kept as a named preset for experiments."""

    enabled: bool = True
    r_1_15: float = 1.25
    r_15_2: float = 1.43
    r_floor: float = 1.10
    min_group: int = 3
    min_shelf: int = 4
    dens_lo: float = 0.9
    dens_hi: float = 1.3
    span_frac: float = 0.8
    min_anchor: int = 3


GEO_BUILD_0810 = GeoParams(r_1_15=1.30, r_15_2=1.48)
GEO_ENUM: dict[str, list[str]] = {
    "Буратино": ["ПЭТ 1 л", "ПЭТ 1,5 л", "ПЭТ 2 л"],
    "Компотай": ["ПЭТ 1 л", "ПЭТ 1,5 л"],
}


def _loc(x: float) -> str:
    return "слева" if x < 333 else "центр" if x < 667 else "справа"


def build_items(boxes: list[Box]) -> list[dict]:
    """(shelf, brand, subtype, format) groups -> report items; count = number of boxes."""
    groups: dict[str, dict] = {}
    for b in boxes:
        shelf = shelf_of(b)
        fmt = b.get("format") or None
        key = f"{shelf}|{b['label']}|{b.get('subtype') or ''}|{fmt or ''}"
        if key not in groups:
            groups[key] = {"shelf": shelf, "brand": b["label"], "subtype": b.get("subtype") or None, "format": fmt, "boxes": []}
        groups[key]["boxes"].append(b)
    items = []
    for g in groups.values():
        centers = [(b["box_2d"][1] + b["box_2d"][3]) / 2 for b in g["boxes"]]
        mean_x = sum(centers) / len(centers)
        confs = [b["confidence"] if _is_num(b.get("confidence")) else 1 for b in g["boxes"]]
        items.append({
            "product_name": g["brand"],
            "product_subtype": g["subtype"],
            "package_format": g["format"],
            "shelf_index": g["shelf"],
            "shelf_location": _loc(mean_x),
            "front_facing_count": len(g["boxes"]),
            "confidence": min(confs),
            "_x": mean_x,
        })
    items.sort(key=lambda i: (i["shelf_index"], i["_x"]))
    for i in items:
        del i["_x"]
    return items


def _format_geo(ours: list[Box], geo: GeoParams) -> dict:
    diag: dict[str, Any] = {"enabled": geo.enabled, "anchor": None, "groups": []}
    if not geo.enabled:
        return diag
    by_shelf: dict[int, list[Box]] = {}
    for b in ours:
        by_shelf.setdefault(shelf_of(b), []).append(b)
    meta: dict[int, dict] = {}
    max_span = 0.0
    for s, arr in by_shelf.items():
        span = max(b["box_2d"][3] for b in arr) - min(b["box_2d"][1] for b in arr)
        dens = sum(_width(b) for b in arr) / span if span > 0 else 0
        meta[s] = {"span": span, "dens": dens, "n": len(arr)}
        if span > max_span:
            max_span = span

    def shelf_ok(s: int) -> bool:
        m = meta.get(s)
        return bool(m) and m["n"] >= geo.min_shelf and geo.dens_lo <= m["dens"] <= geo.dens_hi and m["span"] >= geo.span_frac * max_span

    cans = [b for b in ours if b.get("format") == CAN_045 and shelf_ok(shelf_of(b))]
    if len(cans) < geo.min_anchor:
        diag["anchor"] = {"ok": False, "cans": len(cans)}
        return diag
    anchor = _upper_median(_width(b) / meta[shelf_of(b)]["span"] for b in cans)
    diag["anchor"] = {"ok": True, "w_rel": _to_fixed(anchor, 4), "cans": len(cans)}

    tg: dict[str, list[Box]] = {}
    for b in ours:
        allowed = GEO_ENUM.get(b["label"])
        if not allowed:
            continue
        f = b.get("format") or None
        if f is not None and f not in allowed:
            continue
        if not shelf_ok(shelf_of(b)):
            continue
        tg.setdefault(f"{shelf_of(b)}|{b['label']}|{f or 'null'}", []).append(b)
    for k, arr in tg.items():
        brand = k.split("|")[1]
        if len(arr) < geo.min_group:
            diag["groups"].append({"key": k, "n": len(arr), "kept": "мало боксов"})
            continue
        r = _upper_median(_width(b) / meta[shelf_of(b)]["span"] for b in arr) / anchor
        if r < geo.r_floor:
            diag["groups"].append({"key": k, "n": len(arr), "r": _to_fixed(r, 3), "kept": "зона 0,5/1 л"})
            continue
        to = "ПЭТ 1 л" if r < geo.r_1_15 else "ПЭТ 1,5 л" if r < geo.r_15_2 else "ПЭТ 2 л"
        allowed = GEO_ENUM[brand]
        if to not in allowed:
            to = allowed[-1]  # enum cap (Компотай has no 2 l)
        changed = sum(1 for b in arr if (b.get("format") or None) != to)
        for b in arr:
            b["format"] = to
        diag["groups"].append({"key": k, "n": len(arr), "r": _to_fixed(r, 3), "to": to, "changed": changed})
    return diag


def postprocess_detect(data: dict, *, finish_reason: str | None = None, usage: dict | None = None,
                       geo: GeoParams = GeoParams()) -> dict:
    """Pass-1 detections -> n8n «Парсинг» output (items + _detect + _usage). Pure; input is not mutated."""
    boxes_in = data.get("boxes") if isinstance(data.get("boxes"), list) else []
    boxes_in = copy.deepcopy(boxes_in)

    # 1) coordinates: 4 numbers, clamp 0..1000, non-empty
    valid, bad = [], 0
    for b in boxes_in:
        c = b.get("box_2d") if isinstance(b, dict) else None
        if not isinstance(c, list) or len(c) != 4 or any(not _is_num(v) for v in c):
            bad += 1
            continue
        y0, x0, y1, x1 = (_num(max(0, min(1000, v))) for v in c)
        if y1 <= y0 or x1 <= x0:
            bad += 1
            continue
        valid.append({**b, "box_2d": [y0, x0, y1, x1]})

    # 2) IoU > 0.7 dedup, higher confidence wins (stable sort like V8)
    valid.sort(key=_conf_or_zero, reverse=True)
    kept_all: list[Box] = []
    dups = 0
    for b in valid:
        if any(iou(k["box_2d"], b["box_2d"]) > 0.7 for k in kept_all):
            dups += 1
            continue
        kept_all.append(b)

    # 2b) slivers: interior box narrower than 0.7 x median width of its shelf
    widths: dict[int, list[float]] = {}
    for b in kept_all:
        widths.setdefault(shelf_of(b), []).append(_width(b))
    med_w = {s: _upper_median(ws) for s, ws in widths.items()}
    slivers: list[Box] = []
    kept: list[Box] = []
    for b in kept_all:
        med = med_w.get(shelf_of(b)) or 0
        at_edge = b["box_2d"][1] <= 5 or b["box_2d"][3] >= 995
        if not at_edge and med > 0 and _width(b) < 0.7 * med:
            slivers.append(b)
        else:
            kept.append(b)

    # 3) foreign -> diagnostics only
    foreign = [b for b in kept if b.get("label") == FOREIGN]
    ours = [b for b in kept if b.get("label") in BRANDS]

    # 3b) format_geo (mutates format of ours; `kept` shares the dicts, like JS)
    geo_diag = _format_geo(ours, geo)

    items = build_items(ours)
    return {
        "shelves_with_target_product": len({i["shelf_index"] for i in items}),
        "items": items,
        "store_code_on_card": data.get("store_code_on_card"),
        "overall_confidence": data["overall_confidence"] if _is_num(data.get("overall_confidence")) else None,
        "notes": data.get("notes") or "",
        "_detect": {
            "boxes_total": len(boxes_in),
            "boxes_bad": bad,
            "dedup_dropped": dups,
            "slivers_dropped": len(slivers),
            "slivers_raw": slivers,
            "foreign_units": len(foreign),
            "format_null": sum(1 for b in ours if not b.get("format")),
            "format_geo": geo_diag,
            "finish_reason": finish_reason,
            "boxes_raw": kept,
        },
        "_usage": usage or {"prompt_tokens": None, "cached_tokens": None, "output_tokens": None},
    }


def parse_detect_response(raw: dict, geo: GeoParams = GeoParams()) -> dict:
    data, finish = extract_text_json(raw)
    u = usage_of(raw)
    return postprocess_detect(data, finish_reason=finish,
                              usage={k: u[k] for k in ("prompt_tokens", "cached_tokens", "output_tokens")}, geo=geo)


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    iy = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    inter = ix * iy
    union = (a[3] - a[1]) * (a[2] - a[0]) + (b[3] - b[1]) * (b[2] - b[0]) - inter
    return inter / union if union > 0 else 0


# ---------------------------------------------------------------- pass 2 (v9 groups)
def _groups_by_shelf(ours: list[Box]) -> dict[int, list[dict]]:
    """Shelf -> left-to-right runs of equal (label, subtype). Same algorithm in plan and merge."""
    by_shelf: dict[int, list[Box]] = {}
    for b in ours:
        by_shelf.setdefault(shelf_of(b), []).append(b)
    out: dict[int, list[dict]] = {}
    for s, arr in by_shelf.items():
        arr = sorted(arr, key=lambda b: b["box_2d"][1])
        groups, pos = [], 0
        while pos < len(arr):
            brand, sub = arr[pos]["label"], arr[pos].get("subtype") or None
            end = pos
            while end < len(arr) and arr[end]["label"] == brand and (arr[end].get("subtype") or None) == sub:
                end += 1
            groups.append({"group_index": len(groups) + 1, "brand": brand, "subtype": sub, "boxes": arr[pos:end]})
            pos = end
        out[s] = groups
    return out


def plan_groups(boxes_raw: list[Box]) -> list[dict]:
    """Plan for pass 2: [{shelf_index, count, groups:[{group_index, brand, size, subtype}]}] sorted by shelf."""
    ours = [b for b in boxes_raw if b and b.get("label") in BRANDS]
    plan = []
    for s, groups in sorted(_groups_by_shelf(ours).items()):
        plan.append({
            "shelf_index": s,
            "count": sum(len(g["boxes"]) for g in groups),
            "groups": [{"group_index": g["group_index"], "brand": g["brand"], "size": len(g["boxes"]),
                        "subtype": g["subtype"]} for g in groups],
        })
    return plan


def plan_text(plan: list[dict]) -> str:
    return "\n".join(
        f"полка {s['shelf_index']} ({s['count']} шт. слева направо): "
        + "; ".join(f"группа {g['group_index']} — {g['size']} шт., бренд {g['brand']}" for g in s["groups"])
        for s in plan
    )


def is_uncertain_group(g: dict) -> bool:
    """Gate per group: AI TEA with no subtype or a pink-zone name (the only place pass 2 helped)."""
    return g["brand"] == "AI TEA" and (not g.get("subtype") or bool(PINK_RE.search(str(g["subtype"]))))


def uncertain_targets(plan: list[dict], verified: set[tuple[int, int]] | None = None) -> list[tuple[int, int]]:
    verified = verified or set()
    return [(s["shelf_index"], g["group_index"]) for s in plan for g in s["groups"]
            if is_uncertain_group(g) and (s["shelf_index"], g["group_index"]) not in verified]


def merge_verify(parsed: dict, raw_pass2: dict | None, *, targets: Iterable[tuple[int, int]] | None = None,
                 version: str = "v9-groups") -> dict:
    """n8n «Слияние подвидов» v9. `targets=None` = n8n behaviour (all groups may be renamed).
    With targets, only listed (shelf, group_index) can change — the rest is kept as pass 1 said."""
    parsed = copy.deepcopy(parsed)
    target_set = set(targets) if targets is not None else None

    pass2 = None
    if raw_pass2:
        try:
            pass2, _ = extract_text_json(raw_pass2)
        except Exception:  # noqa: BLE001 — n8n: any parse error = "pass 2 did not answer"
            pass2 = None

    kept = (parsed.get("_detect") or {}).get("boxes_raw") or []
    ours = [b for b in kept if b and b.get("label") in BRANDS]
    groups_by_shelf = _groups_by_shelf(ours)

    stats: list[dict] = []
    changed = needs_review = 0
    if pass2 and isinstance(pass2.get("shelves"), list):
        for sh in pass2["shelves"]:
            groups = groups_by_shelf.get(sh.get("shelf_index"))
            if not groups:
                stats.append({"shelf": sh.get("shelf_index"), "applied": False, "reason": "у Flash нет такой полки"})
                continue
            details = []
            for g in sh.get("groups") or []:
                grp = next((x for x in groups if x["group_index"] == g.get("group_index")), None)
                if grp is None:
                    details.append({"gi": g.get("group_index"), "applied": False, "reason": "нет такой группы у Flash"})
                    continue
                if target_set is not None and (sh["shelf_index"], grp["group_index"]) not in target_set:
                    details.append({"gi": g["group_index"], "applied": False, "reason": "группа уверенная — не меняем"})
                    continue
                sub = g.get("subtype")
                nv = sub if (sub and sub != UNKNOWN) else None
                if nv is None:
                    needs_review += 1
                    details.append({"gi": g["group_index"], "applied": False, "reason": "pass2 не уверен — оставлен Flash",
                                    "needs_review": True})
                    continue
                if not str(nv).startswith(grp["brand"]):
                    details.append({"gi": g["group_index"], "applied": False, "reason": "подпись чужого бренда: " + str(nv)})
                    continue
                c = 0
                for b in grp["boxes"]:
                    if (b.get("subtype") or None) != nv:
                        c += 1
                    b["subtype"] = nv
                changed += c
                details.append({"gi": g["group_index"], "applied": True, "changed": c, "name": nv})
            stats.append({"shelf": sh["shelf_index"], "applied": any(d.get("applied") for d in details), "groups": details})
    else:
        stats.append({"shelf": None, "applied": False, "reason": "проход 2 не ответил или ответ не разобрался"})

    items = build_items(ours)
    u = usage_of(raw_pass2 or {})
    parsed.update({
        "items": items,
        "shelves_with_target_product": len({i["shelf_index"] for i in items}),
        "_pass2": {
            "version": version,
            "shelves_applied": sum(1 for s in stats if s.get("applied")),
            "shelves_total": len(groups_by_shelf),
            "subtypes_changed": changed,
            "needs_review": needs_review,
            "detail": stats,
            "usage": {"prompt_tokens": u["prompt_tokens"] or None, "cached_tokens": u["cached_tokens"] or None,
                      "output_tokens": u["output_tokens"] or None},
        },
    })
    return parsed


def needs_review_groups(merged: dict) -> set[tuple[int, int]]:
    out = set()
    for s in (merged.get("_pass2") or {}).get("detail") or []:
        for d in s.get("groups") or []:
            if d.get("needs_review") or str(d.get("reason", "")).startswith("подпись чужого бренда"):
                out.add((s["shelf"], d["gi"]))
    return out


def as_dict(obj: Any) -> Any:  # small helper for dataclasses in diagnostics
    return asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj
