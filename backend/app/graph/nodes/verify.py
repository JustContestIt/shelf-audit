"""Uncertain groups -> retrieve_refs (visual RAG) -> verify_subtypes (pass 2), bounded loop."""
from __future__ import annotations

import json
from pathlib import Path

from app.catalog import subtype_enum
from app.graph.deps import Deps
from app.graph.state import AuditState, Progress
from app.guardrails.output_schema import validate_verify
from app.vision.crops import b64, crop_box, load_image
from app.vision.llm import LLMError, call_llm
from app.vision.postprocess import (
    _groups_by_shelf,
    extract_text_json,
    is_uncertain_group,
    merge_verify,
    needs_review_groups,
    plan_groups,
)
from app.vision.requests import photo_part, verify_request

MAX_CROPS_PER_GROUP = 3


def _bkey(b: dict) -> str:
    return json.dumps(b["box_2d"])


def uncertain_groups(state: AuditState) -> list[tuple[int, int]]:
    """Groups of the current (merged) boxes that are uncertain AND contain a box pass 2 has not seen."""
    boxes = (state.merged.get("_detect") or {}).get("boxes_raw") or []
    ours = [b for b in boxes if b.get("label") in ("Буратино", "AI TEA", "Chino", "Компотай", "Tamga")]
    seen = set(state.verified_boxes)
    out = []
    for shelf, groups in sorted(_groups_by_shelf(ours).items()):
        for g in groups:
            if is_uncertain_group(g) and any(_bkey(b) not in seen for b in g["boxes"]):
                out.append((shelf, g["group_index"]))
    return out


def make_route_uncertain(deps: Deps):
    s = deps.settings

    def route(state: AuditState) -> str:
        if state.status == "failed" or s.pass2_mode == "off":
            return "build_report"
        if state.verify_attempts >= s.max_verify_iterations:
            return "build_report"
        if s.pass2_mode == "always" and state.verify_attempts == 0:
            return "retrieve_refs"
        return "retrieve_refs" if uncertain_groups(state) else "build_report"

    return route


def make_route_after_retrieve(deps: Deps):
    """pass2_mode=check: RAG runs for the ours/foreign check only, pass-1 names stay (A/B-2 arm «pass 1 + check»)."""
    def route(state: AuditState) -> str:
        return "build_report" if deps.settings.pass2_mode == "check" else "verify_subtypes"
    return route


def make_retrieve_refs(deps: Deps):
    s = deps.settings

    def retrieve_refs(state: AuditState) -> dict:
        targets = uncertain_groups(state)
        if s.pass2_mode == "always" and state.verify_attempts == 0:
            plan = plan_groups((state.merged.get("_detect") or {}).get("boxes_raw") or [])
            targets = [(p["shelf_index"], g["group_index"]) for p in plan for g in p["groups"]]
        info = f"неуверенных групп: {len(targets)}"
        if deps.retriever is None:
            return {"uncertain": [list(t) for t in targets], "retrieval": {"_mode": "all"},
                    "progress": [Progress(node="retrieve_refs", info=f"{info}; индекс эталонов не собран — все эталоны")]}
        mode = "topk" if s.pass2_refs == "topk" else "all"
        im = load_image(state.photo.path)
        boxes = (state.merged.get("_detect") or {}).get("boxes_raw") or []
        groups = _groups_by_shelf([b for b in boxes if b.get("label") in ("Буратино", "AI TEA", "Chino", "Компотай", "Tamga")])
        retrieval: dict = {"_mode": mode, "_backend": deps.retriever.backend}
        suspected = set(state.suspected_boxes)
        n_susp = 0
        for shelf, gi in targets:
            g = next(x for x in groups[shelf] if x["group_index"] == gi)
            sample = g["boxes"][:: max(1, len(g["boxes"]) // MAX_CROPS_PER_GROUP)][:MAX_CROPS_PER_GROUP]
            crops = [crop_box(im, b["box_2d"]) for b in sample]
            r = deps.retriever.retrieve(crops, brand=g["brand"], k=s.rag_top_k, exclude_keys=s.exclude_keys)
            susp = bool(s.foreign_check and r.siglip_max is not None and not g["subtype"]
                        and r.siglip_max < s.foreign_sim_threshold)
            if susp:
                suspected |= {_bkey(b) for b in g["boxes"]}
                n_susp += len(g["boxes"])
            retrieval[f"{shelf}.{gi}"] = {
                "brand": g["brand"], "pass1": g["subtype"], "size": len(g["boxes"]),
                "siglip_max": None if r.siglip_max is None else round(r.siglip_max, 4), "suspected_foreign": susp,
                "candidates": [{"canon_name": c.canon_name, "score": round(c.score, 3), "s_siglip": round(c.s_siglip, 4),
                                "s_hsv": round(c.s_hsv, 4), "refs": [x.key for x in c.refs]} for c in r.candidates],
            }
        refs_info = f"top-{s.rag_top_k} эталонов" if mode == "topk" else "все эталоны в проход 2 (A/B-1 baseline)"
        return {"uncertain": [list(t) for t in targets], "retrieval": retrieval, "suspected_boxes": sorted(suspected),
                "progress": [Progress(node="retrieve_refs", info=f"{info}; {refs_info} ({deps.retriever.backend})"
                                      + (f"; похожи на чужой товар: {n_susp} ед." if n_susp else ""))]}

    return retrieve_refs


def _refs_for_pass2(deps: Deps, retrieval: dict) -> list:
    active = deps.active_refs()
    if retrieval.get("_mode") != "topk":
        return active
    by_key = {r.key: r for r in deps.catalog_refs()} | {r.key: r for r in active}
    want: list[str] = []
    for k, v in retrieval.items():
        if k.startswith("_"):
            continue
        for c in v["candidates"]:
            want += c["refs"]
    picked, seen = [], set()
    for key in want:
        if key in by_key and key not in seen:
            seen.add(key)
            picked.append(by_key[key])
    from app.catalog import sort_refs

    return sort_refs(picked) or active


def make_verify_subtypes(deps: Deps):
    s = deps.settings

    def verify_subtypes(state: AuditState) -> dict:
        boxes = (state.merged.get("_detect") or {}).get("boxes_raw") or []
        targets = [tuple(t) for t in state.uncertain]
        refs = _refs_for_pass2(deps, state.retrieval)
        prompt = deps.verify_prompt
        photo = photo_part(b64(Path(state.photo.path).read_bytes()), state.photo.mime, s.media_resolution or "MEDIA_RESOLUTION_ULTRA_HIGH")
        body, plan = verify_request(boxes, refs, photo, prompt.text, deps.gen(), deps.ref_parts, enum_refs=deps.active_refs())
        key = deps.cache_key("verify", state.photo.sha256, refs=[r.key for r in refs],
                             plan=[[p["shelf_index"], [[g["group_index"], g["size"], g["brand"]] for g in p["groups"]]] for p in plan],
                             attempt=state.verify_attempts)
        attempted = [_bkey(b) for shelf, gi in targets for b in _group_boxes(boxes, shelf, gi)]
        upd: dict = {"verify_attempts": state.verify_attempts + 1, "verified_boxes": state.verified_boxes + attempted,
                     "verify_prompt_version": prompt.version}
        try:
            res = call_llm(deps.verify_llm, body, pass_name="verify", cache_key=key)
        except LLMError as e:
            merged = _local_fallback(state, targets)
            nr = sorted(set(map(tuple, state.needs_review_groups)) | set(targets))
            return {**upd, "merged": merged, "needs_review_groups": [list(t) for t in nr],
                    "errors": [f"verify: {e}"[:500]],
                    "progress": [Progress(node="verify_subtypes", info="проход 2 не ответил — локальный ансамбль, needs_review")]}
        from app.graph.nodes.detect import llm_call_record

        try:
            data, _ = extract_text_json(res["raw"])
            issues = validate_verify(data, subtype_enum(deps.active_refs()))
        except Exception as e:  # noqa: BLE001
            issues = [f"verify: ответ не разобрался: {e}"]
        merged = merge_verify(state.merged, res["raw"], targets=None if s.pass2_mode == "always" else targets,
                              version=prompt.version)
        nr = set(map(tuple, state.needs_review_groups)) | needs_review_groups(merged)
        p2 = merged["_pass2"]
        return {**upd, "merged": merged, "needs_review_groups": [list(t) for t in sorted(nr)],
                "llm_calls": [llm_call_record(res)], "errors": [f"output_guard: {i}" for i in issues],
                "progress": [Progress(node="verify_subtypes",
                                      info=f"групп {len(targets)}, эталонов {len(refs)}, изменено {p2['subtypes_changed']}, "
                                           f"не уверен {p2['needs_review']}" + (" (replay)" if res["replayed"] else ""))]}

    return verify_subtypes


def _group_boxes(boxes: list[dict], shelf: int, gi: int) -> list[dict]:
    groups = _groups_by_shelf([b for b in boxes if b.get("label") in ("Буратино", "AI TEA", "Chino", "Компотай", "Tamga")])
    return next((g["boxes"] for g in groups.get(shelf, []) if g["group_index"] == gi), [])


def _local_fallback(state: AuditState, targets: list[tuple[int, int]]) -> dict:
    """No LLM for pass 2: take the RAG ensemble top-1 for uncertain groups, mark them needs_review."""
    retrieval = state.retrieval or {}
    shelves = {}
    for shelf, gi in targets:
        cands = (retrieval.get(f"{shelf}.{gi}") or {}).get("candidates") or []
        if cands:
            shelves.setdefault(shelf, []).append({"group_index": gi, "subtype": cands[0]["canon_name"]})
    raw = {"candidates": [{"content": {"parts": [{"text": json.dumps(
        {"shelves": [{"shelf_index": k, "groups": v} for k, v in shelves.items()]}, ensure_ascii=False)}]}}]}
    return merge_verify(state.merged, raw, targets=targets, version="local-ensemble")
