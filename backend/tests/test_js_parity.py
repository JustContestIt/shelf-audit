"""Python port vs the original n8n JS, on recorded runs and on randomized inputs.

"The same result as the n8n node" is checked literally: the JS body of the node is executed
in Node with a mocked n8n context (tests/js_parity/run_node.js) and the outputs are compared
as JSON.
"""
from __future__ import annotations

import json
import random

import pytest
from conftest import roundtrip, run_js

from app.vision import postprocess as pp

BRANDS = list(pp.BRANDS)
SUBS = {
    "AI TEA": ["AI TEA малина", "AI TEA персик-жасмин", "AI TEA клубника-киви", "AI TEA помело-цветок апельсина",
               "AI TEA манго-маракуйя", "AI TEA лимон-лайм-жасмин", None],
    "Буратино": ["Буратино классический", "Буратино гранат", None],
    "Компотай": ["Компотай вишневый", "Компотай классический", None],
    "Chino": ["Chino Bellini", None],
    "Tamga": [None],
}
FORMATS = ["банка 0,45 л", "ПЭТ 0,5 л", "ПЭТ 1 л", "ПЭТ 1,5 л", "ПЭТ 2 л", None]


def gemini_raw(data: dict, finish="STOP", usage=None) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(data, ensure_ascii=False)}]}, "finishReason": finish}],
            "usageMetadata": usage or {"promptTokenCount": 50000, "cachedContentTokenCount": 40000, "candidatesTokenCount": 5000}}


def js_parse(raws: list[dict]) -> list[dict]:
    res = run_js([{"node": "parse_v7_5.js", "input": r} for r in raws])
    return [r[0]["json"] for r in res]


def js_merge(pairs: list[tuple[dict, dict]]) -> list[dict]:
    res = run_js([{"node": "merge_v9.js", "input": raw2, "nodes": {"Парсинг обработки Google Vision": {"json": parsed}}}
                  for parsed, raw2 in pairs])
    return [r[0]["json"] for r in res]


# ------------------------------------------------------------------ recorded runs
def _raw_from_recorded(p1: dict) -> dict:
    d = p1["_detect"]
    boxes = list(d.get("boxes_raw") or []) + list(d.get("slivers_raw") or [])
    data = {"boxes": boxes, "store_code_on_card": p1.get("store_code_on_card"),
            "overall_confidence": p1.get("overall_confidence", 0.9), "notes": p1.get("notes", "")}
    return gemini_raw(data)


def test_parse_matches_js_on_recorded_runs(n8n_runs):
    raws = [_raw_from_recorded(r["pass1"]) for _, r in n8n_runs]
    js = js_parse(raws)
    for (name, _), raw, j in zip(n8n_runs, raws, js, strict=True):
        py = roundtrip(pp.parse_detect_response(raw))
        assert py == j, f"parse differs from n8n JS on {name}"


def test_parse_reproduces_recorded_items(n8n_runs):
    """Where the run has the full node output (test results/), items must match the recorded ones."""
    checked = 0
    for name, r in n8n_runs:
        p1 = r["pass1"]
        if "items" not in p1:
            continue
        py = pp.parse_detect_response(_raw_from_recorded(p1))
        assert roundtrip(py["items"]) == p1["items"], name
        assert py["_detect"]["slivers_dropped"] == p1["_detect"]["slivers_dropped"], name
        assert py["_detect"]["foreign_units"] == p1["_detect"]["foreign_units"], name
        checked += 1
    assert checked >= 3


def _pass2_raw_from_detail(p2: dict) -> dict | None:
    """Rebuild the pass-2 model answer from _pass2.detail (names per shelf/group)."""
    det = (p2.get("_pass2") or {}).get("detail") or []
    shelves = []
    for s in det:
        if s.get("shelf") is None:
            return None
        groups = []
        for g in s.get("groups") or []:
            if g.get("applied"):
                groups.append({"group_index": g["gi"], "subtype": g["name"]})
            elif g.get("needs_review"):
                groups.append({"group_index": g["gi"], "subtype": pp.UNKNOWN})
            elif str(g.get("reason", "")).startswith("подпись чужого бренда: "):
                groups.append({"group_index": g["gi"], "subtype": g["reason"].split(": ", 1)[1]})
        shelves.append({"shelf_index": s["shelf"], "groups": groups})
    return gemini_raw({"shelves": shelves}, usage={"promptTokenCount": 53500, "candidatesTokenCount": 900})


def test_merge_matches_js_and_recorded_final(n8n_runs):
    cases = []
    for name, r in n8n_runs:
        if not r.get("pass2") or not (r["pass2"].get("_pass2") or {}).get("detail"):
            continue
        raw2 = _pass2_raw_from_detail(r["pass2"])
        if raw2 is None:
            continue
        cases.append((name, r, raw2))
    assert len(cases) >= 20
    js = js_merge([(c[1]["pass1"], c[2]) for c in cases])
    for (name, r, raw2), j in zip(cases, js, strict=True):
        py = roundtrip(pp.merge_verify(r["pass1"], raw2))
        assert py == j, f"merge differs from n8n JS on {name}"
        # and the final subtypes equal what n8n recorded after pass 2
        rec = [(b["box_2d"], b.get("subtype")) for b in r["pass2"]["_detect"]["boxes_raw"] if b.get("label") in pp.BRANDS]
        got = [(b["box_2d"], b.get("subtype")) for b in py["_detect"]["boxes_raw"] if b.get("label") in pp.BRANDS]
        assert sorted(map(json.dumps, got)) == sorted(map(json.dumps, rec)), f"final boxes differ from recorded on {name}"
        assert py["_pass2"]["subtypes_changed"] == r["pass2"]["_pass2"]["subtypes_changed"], name


# ------------------------------------------------------------------ randomized
def _random_frame(rng: random.Random) -> dict:
    boxes = []
    n_shelves = rng.randint(1, 5)
    for s in range(1, n_shelves + 1):
        y0 = 80 + (s - 1) * 180
        x = rng.randint(0, 60)
        brand = rng.choice(BRANDS)
        fmt = rng.choice(FORMATS)
        for _ in range(rng.randint(1, 14)):
            if rng.random() < 0.25:
                brand = rng.choice(BRANDS)
                fmt = rng.choice(FORMATS)
            w = rng.choice([rng.randint(35, 60), rng.randint(8, 30)]) if rng.random() < 0.15 else rng.randint(38, 70)
            label = pp.FOREIGN if rng.random() < 0.07 else brand
            sub = None if label == pp.FOREIGN else rng.choice(SUBS[brand])
            box = [y0 + rng.randint(-3, 3), x, y0 + rng.randint(90, 140), min(1000, x + w)]
            if rng.random() < 0.05:
                box = [box[0], box[1], box[0] - 5, box[3]]  # invalid
            if rng.random() < 0.03:
                box = [box[0], box[1], box[2], "x"]  # not a number
            b = {"box_2d": box, "label": label, "subtype": sub, "format": fmt if brand not in ("Chino", "Tamga") else None,
                 "shelf_index": s if rng.random() > 0.03 else rng.choice([0, None, 1.0, -1]),
                 "confidence": rng.choice([0.95, 0.98, 0.9, 0.7, None])}
            boxes.append(b)
            if rng.random() < 0.08:  # near-duplicate box
                boxes.append({**b, "box_2d": [v + rng.randint(-2, 2) if isinstance(v, int) else v for v in box],
                              "confidence": rng.choice([0.5, 0.99])})
            x = x + w - rng.randint(0, 4)
            if x > 990:
                break
    return {"boxes": boxes, "overall_confidence": rng.choice([0.9, 0.7, None]), "notes": "fuzz",
            "store_code_on_card": rng.choice([None, "231"])}


@pytest.mark.parametrize("seed", [0, 1])
def test_parse_and_merge_fuzz_parity(seed):
    rng = random.Random(seed)
    raws = [gemini_raw(_random_frame(rng)) for _ in range(150)]
    js = js_parse(raws)
    parsed_py = []
    for i, (raw, j) in enumerate(zip(raws, js, strict=True)):
        py = roundtrip(pp.parse_detect_response(raw))
        assert py == j, f"fuzz parse #{i} (seed {seed}) differs"
        parsed_py.append(py)

    pairs = []
    for parsed in parsed_py:
        plan = pp.plan_groups(parsed["_detect"]["boxes_raw"])
        shelves = []
        for s in plan:
            gs = []
            for g in s["groups"]:
                if rng.random() < 0.8:
                    choice = rng.choice(SUBS.get(g["brand"], [None]) + [pp.UNKNOWN, "AI TEA малина", "Компотай вишневый"])
                    gs.append({"group_index": g["group_index"], "subtype": choice or pp.UNKNOWN})
            if rng.random() < 0.1:
                gs.append({"group_index": 99, "subtype": "AI TEA малина"})
            shelves.append({"shelf_index": s["shelf_index"], "groups": gs})
        if rng.random() < 0.1:
            shelves.append({"shelf_index": 42, "groups": []})
        raw2 = None if rng.random() < 0.05 else gemini_raw({"shelves": shelves})
        pairs.append((parsed, raw2 or {}))
    jsm = js_merge(pairs)
    for i, ((parsed, raw2), j) in enumerate(zip(pairs, jsm, strict=True)):
        py = roundtrip(pp.merge_verify(parsed, raw2))
        assert py == j, f"fuzz merge #{i} (seed {seed}) differs"


def test_plan_matches_js_verify_request(n8n_runs):
    """Grouping used by the pass-2 plan == «Сборка запроса Pro» v9 (v9_plan)."""
    catalog = [{"key": "aitea_malina", "brand": "AI TEA", "canon_name": "AI TEA малина", "file_url": f"files/x{i}",
                "mime_type": "image/png"} for i in range(25)]
    reqs, plans = [], []
    for _, r in n8n_runs[:12]:
        p1 = r["pass1"]
        reqs.append({"node": "verify_request_v9.js", "input": p1,
                     "nodes": {"Каталог брендов: Config": {"json": catalog},
                               "Загрузка фото": {"json": {}, "binary": {"data": {"mimeType": "image/jpeg"}}},
                               "Закрепляю тип фотографии": {"json": {"file_mime": "image/jpeg"}},
                               "Перевод фото в строку": {"json": {"data": "AAAA"}}}})
        plans.append([{**s, "groups": [{k: v for k, v in g.items() if k != "subtype"} for g in s["groups"]]}
                      for s in pp.plan_groups(p1["_detect"]["boxes_raw"])])
    for res, plan in zip(run_js(reqs), plans, strict=True):
        assert res[0]["json"]["v9_plan"] == plan


def _geo_frame(rng: random.Random) -> dict:
    """Dense full-width rows: cans 0,45 as the anchor + big PET groups (exercises format_geo)."""
    boxes, w0 = [], rng.randint(40, 60)
    n_shelves = rng.randint(3, 5)
    can_shelves = rng.sample(range(1, n_shelves + 1), k=rng.randint(1, 2))
    for s in range(1, n_shelves + 1):
        y0 = 60 + (s - 1) * 190
        if s in can_shelves:
            brand, fmt, w = "AI TEA", "банка 0,45 л", w0
        else:
            brand = rng.choice(["Буратино", "Компотай", "Буратино"])
            fmt = rng.choice([None, "ПЭТ 1 л", "ПЭТ 1,5 л", "ПЭТ 2 л", "ПЭТ 0,5 л"])
            w = round(w0 * rng.uniform(0.95, 1.75))
        x = rng.randint(20, 80)
        while x + w < 960:
            ww = max(10, w + rng.randint(-3, 3))
            boxes.append({"box_2d": [y0, x, y0 + 150, x + ww], "label": brand,
                          "subtype": SUBS[brand][0], "format": fmt, "shelf_index": s, "confidence": 0.95})
            x += ww - rng.randint(0, 2)
    return {"boxes": boxes, "overall_confidence": 0.9, "notes": ""}


def test_format_geo_fuzz_parity():
    rng = random.Random(7)
    raws = [gemini_raw(_geo_frame(rng)) for _ in range(200)]
    js = js_parse(raws)
    converted = 0
    for i, (raw, j) in enumerate(zip(raws, js, strict=True)):
        py = roundtrip(pp.parse_detect_response(raw))
        assert py == j, f"geo fuzz #{i} differs"
        converted += any("to" in g for g in py["_detect"]["format_geo"]["groups"])
    assert converted > 50  # the generator really exercises the geo branch
