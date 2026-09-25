"""Request bodies and prompt texts == what n8n sent (checked against the original JS)."""
from __future__ import annotations

from conftest import run_js

from app.catalog import is_excluded, load_active_refs, sort_refs
from app.prompts import available, load_prompt
from app.vision.requests import GenConfig, detect_request, photo_part, verify_request


def _rows_and_nodes():
    refs = load_active_refs()
    rows = [{"key": r.key, "brand": r.brand, "canon_name": r.canon_name, "variant": r.variant,
             "mime_type": r.mime_type, "file_url": "https://example.test/files/" + r.key} for r in refs]
    nodes = {"Каталог брендов: Config": {"json": rows},
             "Загрузка фото": {"json": {}, "binary": {"data": {"mimeType": "image/jpeg"}}},
             "Закрепляю тип фотографии": {"json": {"file_mime": "image/jpeg"}},
             "Перевод фото в строку": {"json": {"data": "QUJD"}}}
    return refs, nodes


def _ref_part(r):
    return {"file_data": {"mime_type": r.mime_type, "file_uri": "https://example.test/files/" + r.key}}


def test_prompts_load():
    ids = available()
    for pid in ("detect_v7.4", "detect_v7.5", "verify_v9", "verify_v9_groups"):
        assert pid in ids
        p = load_prompt(pid)
        assert p.version and len(p.text) > 1000


def test_detect_body_equals_n8n_js():
    refs, nodes = _rows_and_nodes()
    js = run_js([{"node": "detect_request_v7_4.js", "input": {}, "nodes": nodes}])[0][0]["json"]
    active = sort_refs([r for r in refs if not is_excluded(r.key, ["aitea_reven"])])
    body = detect_request(active, photo_part("QUJD", "image/jpeg", "MEDIA_RESOLUTION_ULTRA_HIGH"),
                          load_prompt("detect_v7.4").text, GenConfig(temperature=0), _ref_part)
    assert js["refs_count"] == len(active) == 46
    assert body == js["gemini_body"]


def test_verify_body_equals_n8n_js(n8n_runs):
    refs, nodes = _rows_and_nodes()
    active = sort_refs([r for r in refs if not is_excluded(r.key, ["aitea_reven"])])
    for _, run in n8n_runs[:5]:
        p1 = run["pass1"]
        js = run_js([{"node": "verify_request_v9.js", "input": p1, "nodes": nodes}])[0][0]["json"]
        body, plan = verify_request(p1["_detect"]["boxes_raw"], active,
                                    photo_part("QUJD", "image/jpeg", "MEDIA_RESOLUTION_ULTRA_HIGH"),
                                    load_prompt("verify_v9_groups").text, GenConfig(temperature=0), _ref_part)
        assert body == js["gemini_body"]


def test_v75_is_v74_plus_bgcolor_only():
    a, b = load_prompt("detect_v7.4").text, load_prompt("detect_v7.5").text
    assert "ЦВЕТ ФОНА ЭТИКЕТКИ — ЖЁСТКОЕ ОГРАНИЧЕНИЕ" in b and "ЦВЕТ КОРПУСА" not in b
    assert "«КЛУБНИКА + КИВИ»" in b
    # everything outside the SUBTYPE block is untouched
    assert a.split("SUBTYPE —")[0] == b.split("SUBTYPE —")[0]
    assert a.split("FORMAT —")[1] == b.split("FORMAT —")[1]
