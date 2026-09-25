"""The LangGraph pipeline end to end with scripted model answers (recorded n8n runs of IMG_0644).

Checks: routing, the bounded verify loop, interrupt/resume on human_review, retake loop,
rejects, LLM failure -> local fallback, persistence and the "чужие = 0" gate.
"""
from __future__ import annotations

import io
import json

import numpy as np
import pytest
from conftest import load_runs
from PIL import Image

from app.config import Settings
from app.graph.deps import build_deps
from app.graph.state import Store
from app.service import AuditService
from app.storage.repo import MemoryRepo
from app.vision.llm import FallbackChain, LLMError, LLMResult
from app.vision.postprocess import UNKNOWN


def photo_bytes(w=1600, h=1200, seed=0, blur=False) -> bytes:
    rng = np.random.default_rng(seed)
    arr = (rng.random((h, w, 3)) * 255).astype(np.uint8)
    if blur:
        arr[:] = 128
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def raw_json(data: dict, usage=(50000, 5000)) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(data, ensure_ascii=False)}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": usage[0], "candidatesTokenCount": usage[1], "cachedContentTokenCount": 40000}}


class ScriptedLLM:
    def __init__(self, name, answers, fail=False):
        self.name = name
        self.answers = list(answers)
        self.calls: list[dict] = []
        self.fail = fail

    def generate(self, body, *, cache_key=None):
        self.calls.append(body)
        if self.fail:
            raise LLMError("scripted failure", 503, True)
        raw = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return LLMResult(raw, "gemini-3.5-flash", "scripted", 1.0, {"input_tokens": 50000, "output_tokens": 5000, "cached_tokens": 40000},
                         0.05)


@pytest.fixture
def run0644():
    runs = dict(load_runs())
    r = runs["bench_test1_run_01"]
    return r


def _service(tmp_path, detect, verify, **settings):
    s = Settings(photos_dir=tmp_path / "uploads", database_url=None, llm_mode="replay", replay_dir=tmp_path / "cache",
                 catalog_path=tmp_path / "none.jsonl", data_dir=tmp_path, **settings)
    repo = MemoryRepo()
    deps = build_deps(s, repo=repo, retriever=None, detect_llm=detect, verify_llm=verify)
    return AuditService(deps=deps, settings=s), repo


def _detect_answer(run):
    d = run["pass1"]["_detect"]
    return raw_json({"boxes": d["boxes_raw"] + d.get("slivers_raw", []), "overall_confidence": 0.9, "notes": ""})


def _verify_answer(run, unknown_all=False):
    shelves = []
    for s in run["pass2"]["_pass2"]["detail"]:
        gs = []
        for g in s.get("groups", []):
            if unknown_all:
                gs.append({"group_index": g["gi"], "subtype": UNKNOWN})
            elif g.get("applied"):
                gs.append({"group_index": g["gi"], "subtype": g["name"]})
        shelves.append({"shelf_index": s["shelf"], "groups": gs})
    return raw_json({"shelves": shelves}, usage=(53500, 900))


def test_happy_path_interrupt_and_approve(tmp_path, run0644):
    det, ver = ScriptedLLM("d", [_detect_answer(run0644)]), ScriptedLLM("v", [_verify_answer(run0644)])
    svc, repo = _service(tmp_path, det, ver)
    rid = svc.submit(photo_bytes(), "IMG.jpg", Store(store_code="00-0000007", store_name="Демо-точка 7"), wait=True)
    st = svc.state(rid)
    assert st["status"] == "awaiting_review" and st["waiting_review"]
    nodes = [p["node"] for p in st["progress"]]
    assert nodes[:4] == ["validate_input", "input_guard", "detect", "postprocess"]
    assert "retrieve_refs" in nodes and "verify_subtypes" in nodes and nodes[-1] == "build_report"
    rec = repo.get_report(rid)
    rep = rec["body"]["report"]
    assert rec["status"] == "awaiting_review"
    assert rep["total_units"] == 53  # IMG_0644 / AITEA_5SHELF: 53 own units, 5 foreign never counted
    assert all(r["brand"] != "ЧУЖОЙ" for r in rep["rows"])
    # pass 2 got the full plan but only uncertain (pink/null) groups may change
    assert len(ver.calls) == 1
    assert repo.list_reports(status="awaiting_review")[0]["report_id"] == rid
    svc.review(rid, {"action": "approve", "reviewer": "sup"})
    assert repo.get_report(rid)["status"] == "approved"
    assert svc.state(rid)["progress"][-1]["node"] == "persist"
    assert repo.rows_for_export() and all(r["status"] == "утверждено" for r in repo.rows_for_export())


def test_edit_then_persist(tmp_path, run0644):
    svc, repo = _service(tmp_path, ScriptedLLM("d", [_detect_answer(run0644)]), ScriptedLLM("v", [_verify_answer(run0644)]))
    rid = svc.submit(photo_bytes(), "a.jpg", Store(store_code="1"), wait=True)
    n = len(repo.get_report(rid)["body"]["report"]["rows"])
    svc.review(rid, {"action": "edit", "edits": [{"row": 0, "subtype": "AI TEA малина"}, {"row": 1, "delete": True}]})
    rec = repo.get_report(rid)
    assert rec["status"] == "edited" and len(rec["body"]["report"]["rows"]) == n - 1
    assert rec["body"]["report"]["rows"][0]["subtype"] == "AI TEA малина"


def test_retake_loops_to_validate_input(tmp_path, run0644):
    det = ScriptedLLM("d", [_detect_answer(run0644)])
    svc, repo = _service(tmp_path, det, ScriptedLLM("v", [_verify_answer(run0644)]), max_retakes=1)
    rid = svc.submit(photo_bytes(seed=1), "a.jpg", Store(store_code="1"), wait=True)
    svc.retake(rid, photo_bytes(seed=2), "b.jpg", wait=True)
    st = svc.state(rid)
    assert st["status"] == "awaiting_review" and st["retakes"] == 1
    assert [p["node"] for p in st["progress"]].count("validate_input") == 2
    assert len(det.calls) == 2
    # second retake is over the limit -> report is finalised as is
    svc.retake(rid, photo_bytes(seed=3), "c.jpg", wait=True)
    assert repo.get_report(rid)["status"] == "approved"


def test_reject_blurry_and_small(tmp_path, run0644):
    det = ScriptedLLM("d", [_detect_answer(run0644)])
    svc, repo = _service(tmp_path, det, ScriptedLLM("v", [_verify_answer(run0644)]))
    rid = svc.submit(photo_bytes(blur=True), "x.jpg", Store(store_code="1"), wait=True)
    assert repo.get_report(rid)["status"] == "rejected" and "смазано" in repo.get_report(rid)["reject_reason"]
    rid2 = svc.submit(photo_bytes(300, 200), "y.jpg", Store(store_code="1"), wait=True)
    assert "маленькое" in repo.get_report(rid2)["reject_reason"]
    rid3 = svc.submit(b"%PDF-1.4 not an image", "z.pdf", Store(store_code="1"), wait=True)
    assert "не фото" in repo.get_report(rid3)["reject_reason"]
    assert det.calls == []  # the model was never called for rejected input


def test_pass2_failure_uses_local_fallback_and_marks_review(tmp_path, run0644):
    svc, repo = _service(tmp_path, ScriptedLLM("d", [_detect_answer(run0644)]), ScriptedLLM("v", [], fail=True))
    rid = svc.submit(photo_bytes(), "a.jpg", Store(store_code="1"), wait=True)
    rec = repo.get_report(rid)
    assert rec["status"] == "awaiting_review"
    assert any("verify" in f for f in rec["flags"])
    assert rec["body"]["report"]["total_units"] == 53  # counts never depend on pass 2


def test_pass2_off_and_bounded_loop(tmp_path, run0644):
    ver = ScriptedLLM("v", [_verify_answer(run0644, unknown_all=True)])
    svc, repo = _service(tmp_path, ScriptedLLM("d", [_detect_answer(run0644)]), ver, max_verify_iterations=2)
    rid = svc.submit(photo_bytes(), "a.jpg", Store(store_code="1"), wait=True)
    assert len(ver.calls) == 1  # verified boxes are not sent again, the loop ends after one pass
    rep = repo.get_report(rid)["body"]["report"]
    assert rep["needs_review_units"] > 0  # «НЕ ОПРЕДЕЛЁН» groups are flagged, not silently approved (BACKLOG №27)
    ver2 = ScriptedLLM("v", [_verify_answer(run0644)])
    svc2, _ = _service(tmp_path, ScriptedLLM("d", [_detect_answer(run0644)]), ver2, pass2_mode="off")
    svc2.submit(photo_bytes(), "a.jpg", Store(store_code="1"), wait=True)
    assert ver2.calls == []
    # check: retrieval (ours/foreign check) runs for uncertain groups, the LLM pass 2 does not
    ver3 = ScriptedLLM("v", [_verify_answer(run0644)])
    svc3, repo3 = _service(tmp_path, ScriptedLLM("d", [_detect_answer(run0644)]), ver3, pass2_mode="check")
    rid3 = svc3.submit(photo_bytes(), "a.jpg", Store(store_code="1"), wait=True)
    nodes = [p["node"] for p in repo3.get_report(rid3)["body"]["progress"]]
    assert ver3.calls == [] and "retrieve_refs" in nodes and "verify_subtypes" not in nodes
    assert repo3.get_report(rid3)["status"] == "awaiting_review"


def test_detect_failure_is_reported(tmp_path):
    svc, repo = _service(tmp_path, ScriptedLLM("d", [], fail=True), ScriptedLLM("v", [], fail=True))
    rid = svc.submit(photo_bytes(), "a.jpg", Store(store_code="1"), wait=True)
    rec = repo.get_report(rid)
    assert rec["status"] == "failed" and any("detect" in f for f in rec["flags"])


def test_primary_model_down_falls_back_to_next(tmp_path, run0644):
    """«Выключили основную»: the first model of the chain fails, the second answers; the report says so."""
    chain = FallbackChain([ScriptedLLM("gemini-3.5-flash", [], fail=True), ScriptedLLM("gemini-3-flash-preview", [_detect_answer(run0644)])])
    svc, repo = _service(tmp_path, chain, ScriptedLLM("v", [_verify_answer(run0644)]))
    rid = svc.submit(photo_bytes(), "a.jpg", Store(store_code="1"), wait=True)
    rec = repo.get_report(rid)
    assert rec["status"] == "awaiting_review" and rec["body"]["report"]["total_units"] == 53
    det = [c for c in rec["body"]["llm_calls"] if c["pass"] == "detect"][0]
    assert det["fallback_from"] and det["fallback_from"][0].startswith("gemini-3.5-flash")


def test_top_p_reaches_the_request(tmp_path, run0644):
    det = ScriptedLLM("d", [_detect_answer(run0644)])
    svc, _ = _service(tmp_path, det, ScriptedLLM("v", [_verify_answer(run0644)]), top_p=0.95)
    svc.submit(photo_bytes(), "a.jpg", Store(store_code="1"), wait=True)
    assert det.calls[0]["generationConfig"]["topP"] == 0.95
