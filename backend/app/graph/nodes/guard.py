"""validate_input, input_guard, reject."""
from __future__ import annotations

import json
from pathlib import Path

from app.graph.deps import Deps
from app.graph.state import AuditState, Progress
from app.guardrails.input_guard import check_photo, shelf_check_request
from app.vision.crops import b64, telegram_sim, to_jpeg_bytes
from app.vision.llm import LLMError, call_llm
from app.vision.postprocess import extract_text_json
from app.vision.requests import photo_part


def make_validate_input(deps: Deps):
    s = deps.settings

    def validate_input(state: AuditState) -> dict:
        data = Path(state.photo.path).read_bytes()
        pc, _ = check_photo(data, min_side=s.min_side_px, max_mb=s.max_upload_mb, blur_threshold=s.blur_threshold)
        photo = state.photo.model_copy(update={
            "sha256": pc.sha256, "phash": pc.phash, "mime": pc.mime, "width": pc.width, "height": pc.height,
            "bytes": pc.bytes, "blur": pc.blur, "exif": pc.exif})
        guard = {"checks_ok": pc.ok, "reasons": pc.reasons}
        dups = []
        if pc.ok and state.store.store_code:
            try:
                dups = deps.repo.find_duplicates(pc.phash, store_code=state.store.store_code, exclude=state.report_id)
            except Exception:  # noqa: BLE001 — dedup is advisory
                dups = []
        guard["duplicates"] = dups
        upd = {"photo": photo, "guard": guard, "status": "detecting",
               "progress": [Progress(node="validate_input", info=f"{pc.width}×{pc.height}, резкость {pc.blur:.0f}"
                                     + (f", дубль {dups[0]}" if dups else ""))]}
        if not pc.ok:
            upd.update(status="rejected", reject_reason="; ".join(pc.reasons))
        return upd

    return validate_input


def make_input_guard(deps: Deps):
    s = deps.settings

    def input_guard(state: AuditState) -> dict:
        if state.status == "rejected":
            return {"progress": [Progress(node="input_guard", info="пропущено: вход отклонён")]}
        if not (s.shelf_check_llm and deps.guard_llm):
            return {"guard": {**state.guard, "is_shelf": None},
                    "progress": [Progress(node="input_guard", info="LLM-проверка «это полка?» выключена")]}
        from app.vision.crops import load_image

        small = to_jpeg_bytes(telegram_sim(load_image(state.photo.path), 1024, 85))
        body = shelf_check_request(photo_part(b64(small), "image/jpeg", None))
        try:
            res = call_llm(deps.guard_llm, body, pass_name="guard", cache_key=deps.cache_key("guard", state.photo.sha256))
            verdict, _ = extract_text_json(res["raw"])
        except (LLMError, ValueError, json.JSONDecodeError) as e:
            return {"guard": {**state.guard, "is_shelf": None, "error": str(e)[:200]},
                    "errors": [f"input_guard: {e}"[:300]],
                    "progress": [Progress(node="input_guard", info="проверка не ответила — пропускаем дальше")]}
        guard = {**state.guard, **verdict}
        upd: dict = {"guard": guard, "progress": [Progress(node="input_guard", info=verdict.get("kind", ""))]}
        if not verdict.get("is_shelf", True):
            upd.update(status="rejected", reject_reason=f"на фото не полка с товаром ({verdict.get('kind')})")
        return upd

    return input_guard


def route_after_guard(state: AuditState) -> str:
    return "reject" if state.status == "rejected" else "detect"


def make_reject(deps: Deps):
    def reject(state: AuditState) -> dict:
        deps.repo.upsert_report({
            "report_id": state.report_id, "status": "rejected", "store_code": state.store.store_code,
            "store_name": state.store.store_name, "route_code": state.store.route_code, "agent_id": state.store.agent_id,
            "source": state.photo.source, "photo_path": state.photo.path, "photo_sha256": state.photo.sha256,
            "photo_phash": state.photo.phash, "config_id": state.config_id, "reject_reason": state.reject_reason,
            "flags": ["rejected"], "body": {"guard": state.guard},
        })
        return {"status": "rejected", "progress": [Progress(node="reject", info=state.reject_reason or "")]}

    return reject
