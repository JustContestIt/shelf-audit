"""build_report, human_review (interrupt), persist."""
from __future__ import annotations

import json

from langgraph.types import interrupt

from app.catalog import FOREIGN
from app.graph.deps import Deps
from app.graph.state import AuditState, Photo, Progress, Report, ReportRow, Review
from app.vision.postprocess import _groups_by_shelf, build_items, shelf_of


def _row_groups(boxes: list[dict]) -> dict[tuple, list[str]]:
    """(shelf, brand, subtype, format) -> ["shelf.gi", ...] to connect report rows with pass-2 groups."""
    ours = [b for b in boxes if b.get("label") not in (None, FOREIGN)]
    out: dict[tuple, list[str]] = {}
    for shelf, groups in _groups_by_shelf(ours).items():
        for g in groups:
            for b in g["boxes"]:
                k = (shelf_of(b), b["label"], b.get("subtype") or None, b.get("format") or None)
                gk = f"{shelf}.{g['group_index']}"
                if gk not in out.setdefault(k, []):
                    out[k].append(gk)
    return out


def apply_suspected(boxes: list[dict], suspected: set[str], action: str) -> tuple[list[dict], int]:
    """Units of our brand that SigLIP finds unlike any of our refs: relabel to ЧУЖОЙ (exclude) or just mark (flag)."""
    out, n = [], 0
    for b in boxes:
        if json.dumps(b["box_2d"]) in suspected and b.get("label") not in (None, FOREIGN):
            n += 1
            b = {**b, "suspected_foreign": True}
            if action == "exclude":
                b = {**b, "label": FOREIGN, "relabelled_from": b["label"]}
        out.append(b)
    return out, n


def assemble_report(state: AuditState, low_conf: float, foreign_action: str = "exclude") -> Report:
    src = state.merged or state.detect or {}
    det = src.get("_detect") or {}
    boxes, n_susp = apply_suspected(det.get("boxes_raw") or [], set(state.suspected_boxes), foreign_action)
    ours = [b for b in boxes if b.get("label") not in (None, FOREIGN)]
    items = build_items(ours)
    links = _row_groups(boxes)
    nr = {f"{s}.{g}" for s, g in state.needs_review_groups}
    rows = []
    for it in items:
        k = (it["shelf_index"], it["product_name"], it["product_subtype"], it["package_format"])
        gks = links.get(k, [])
        reason = None
        if any(b.get("suspected_foreign") for b in ours if (shelf_of(b), b["label"], b.get("subtype") or None,
                                                              b.get("format") or None) == k):
            reason = "похоже на чужой товар"
        elif it["product_subtype"] is None and it["product_name"] != "Tamga":
            reason = "подвид не опознан"
        elif any(g in nr for g in gks):
            reason = "проход 2 не уверен"
        rows.append(ReportRow(shelf_index=it["shelf_index"], position=it["shelf_location"], brand=it["product_name"],
                              subtype=it["product_subtype"], package_format=it["package_format"],
                              front_facing_count=it["front_facing_count"], needs_review=reason is not None,
                              review_reason=reason, group_keys=gks))
    assert all(r.brand != FOREIGN for r in rows), "contamination gate: ЧУЖОЙ must never be counted"
    conf = src.get("overall_confidence")
    flags = list(dict.fromkeys(e.split(": ", 1)[1] if e.startswith("output_guard: ") else e for e in state.errors))
    if (state.guard or {}).get("duplicates"):
        flags.append("возможный дубль фото: " + ", ".join(state.guard["duplicates"][:3]))
    if n_susp:
        flags.append(f"{n_susp} ед. не похожи на эталоны наших брендов (SigLIP)"
                     + (" — исключены из счёта до проверки" if foreign_action == "exclude" else " — проверьте"))
    if not rows and state.status != "failed":
        flags.append("наш товар на фото не найден")
    cost = sum(c.cost_usd or 0 for c in state.llm_calls)
    lats = [c.latency_s for c in state.llm_calls]
    lat = None if any(x is None for x in lats) else sum(lats)
    return Report(
        rows=rows, total_units=sum(r.front_facing_count for r in rows), shelves=len({r.shelf_index for r in rows}),
        unknown_units=sum(r.front_facing_count for r in rows if r.review_reason == "подвид не опознан"),
        needs_review_units=sum(r.front_facing_count for r in rows if r.needs_review),
        foreign_units=det.get("foreign_units", 0) + (n_susp if foreign_action == "exclude" else 0),
        suspected_foreign_units=n_susp, overall_confidence=conf,
        low_confidence=conf is None or conf < low_conf, flags=flags, cost_usd=round(cost, 5), latency_s=round(lat, 1) if lat is not None else None,
    )


def make_build_report(deps: Deps):
    def build_report(state: AuditState) -> dict:
        rep = assemble_report(state, deps.settings.low_confidence_threshold, deps.settings.foreign_action)
        status = "failed" if state.status == "failed" else "awaiting_review"
        persist_record(deps, state, rep, status)
        return {"report": rep, "status": status,
                "progress": [Progress(node="build_report", info=f"{rep.total_units} ед., строк {len(rep.rows)}, "
                                                               f"на проверку {rep.needs_review_units}")]}

    return build_report


def route_after_report(state: AuditState) -> str:
    return "persist" if state.status == "failed" else "human_review"


def make_human_review(deps: Deps):
    def human_review(state: AuditState) -> dict:
        decision = interrupt({"report_id": state.report_id, "status": "awaiting_review",
                              "report": state.report.model_dump() if state.report else None})
        review = Review.model_validate(decision)
        upd: dict = {"review": review, "progress": [Progress(node="human_review", info=review.action)]}
        if review.action == "retake":
            if state.retakes >= deps.settings.max_retakes or not review.photo_path:
                # guarded in the API as well; here: finish as is, flagged
                upd["status"] = "edited" if review.edits else "approved"
                upd["errors"] = ["retake: лимит пересъёмок исчерпан — отчёт сохранён как есть"]
                return upd
            photo = Photo(path=review.photo_path, source=state.photo.source)
            upd.update({"photo": photo, "status": "retake", "retakes": state.retakes + 1, "detect": {}, "merged": {},
                        "uncertain": [], "verified_boxes": [], "needs_review_groups": [], "retrieval": {}, "suspected_boxes": [],
                        "verify_attempts": 0, "report": None, "reject_reason": None})
            return upd
        if review.action == "edit":
            upd["report"] = apply_edits(state.report, review.edits)
            upd["status"] = "edited"
        else:
            upd["status"] = "approved"
        return upd

    return human_review


def route_after_review(state: AuditState) -> str:
    return "validate_input" if state.status == "retake" else "persist"


def apply_edits(report: Report, edits: list[dict]) -> Report:
    """edits: [{"row": i, "subtype"?: str, "package_format"?: str, "front_facing_count"?: int, "delete"?: bool}]"""
    rows = [r.model_copy() for r in report.rows]
    drop = set()
    for e in edits:
        i = int(e["row"])
        if not 0 <= i < len(rows):
            continue
        if e.get("delete"):
            drop.add(i)
            continue
        upd = {k: e[k] for k in ("subtype", "package_format", "front_facing_count", "brand") if k in e}
        rows[i] = rows[i].model_copy(update={**upd, "needs_review": False, "review_reason": "исправлено супервайзером"})
    rows = [r for i, r in enumerate(rows) if i not in drop]
    return report.model_copy(update={"rows": rows, "total_units": sum(r.front_facing_count for r in rows),
                                     "needs_review_units": sum(r.front_facing_count for r in rows if r.needs_review),
                                     "unknown_units": sum(r.front_facing_count for r in rows if r.subtype is None and r.brand != "Tamga")})


def persist_record(deps: Deps, state: AuditState, rep: Report | None, status: str) -> None:
    det = dict((state.merged or state.detect or {}).get("_detect") or {})
    det["boxes_raw"], _ = apply_suspected(det.get("boxes_raw") or [], set(state.suspected_boxes), deps.settings.foreign_action)
    deps.repo.upsert_report({
        "report_id": state.report_id, "status": status, "store_code": state.store.store_code,
        "store_name": state.store.store_name, "route_code": state.store.route_code, "agent_id": state.store.agent_id,
        "source": state.photo.source, "photo_path": state.photo.path, "photo_sha256": state.photo.sha256,
        "photo_phash": state.photo.phash, "prompt_version": state.prompt_version,
        "verify_prompt_version": state.verify_prompt_version, "config_id": state.config_id,
        "models": ",".join(dict.fromkeys(c.model for c in state.llm_calls)),
        "total_units": rep.total_units if rep else None, "unknown_units": rep.unknown_units if rep else None,
        "needs_review_units": rep.needs_review_units if rep else None,
        "overall_confidence": rep.overall_confidence if rep else None, "low_confidence": rep.low_confidence if rep else None,
        "cost_usd": rep.cost_usd if rep else None, "latency_s": rep.latency_s if rep else None,
        "reject_reason": state.reject_reason, "flags": rep.flags if rep else [],
        "review": state.review.model_dump() if state.review else None,
        "body": {"report": rep.model_dump() if rep else None,
                 "boxes": det.get("boxes_raw") or [], "slivers": det.get("slivers_raw") or [],
                 "photo": {"width": state.photo.width, "height": state.photo.height, "sha256": state.photo.sha256},
                 "retrieval": state.retrieval, "pass2": (state.merged or {}).get("_pass2"),
                 "llm_calls": [json.loads(c.model_dump_json(by_alias=True)) for c in state.llm_calls],
                 "progress": [p.model_dump() for p in state.progress]},
    })


def make_persist(deps: Deps):
    def persist(state: AuditState) -> dict:
        persist_record(deps, state, state.report, state.status)
        return {"progress": [Progress(node="persist", info=state.status)]}

    return persist
