"""API contract with the scripted pipeline (no network, no DB)."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from test_graph import ScriptedLLM, _detect_answer, _service, _verify_answer, photo_bytes, run0644  # noqa: F401

import app.api.main as api


@pytest.fixture
def client(tmp_path, run0644):  # noqa: F811
    svc, repo = _service(tmp_path, ScriptedLLM("d", [_detect_answer(run0644)]), ScriptedLLM("v", [_verify_answer(run0644)]))
    api._service = svc
    api._seed_demo_routes(svc)
    with TestClient(api.app) as c:
        yield c
    api._service = None


def _wait(c, rid, want=("awaiting_review", "rejected", "failed", "approved"), t=10):
    t0 = time.time()
    while time.time() - t0 < t:
        st = c.get(f"/photos/{rid}/status").json()
        if st["status"] in want and not st.get("running"):
            return st
        time.sleep(0.05)
    raise AssertionError(st)


def test_photo_to_approved(client):
    r = client.post("/photos", files={"file": ("IMG.jpg", photo_bytes(), "image/jpeg")},
                    data={"store_code": "00-0000001", "store_name": "Демо-точка 1", "agent_id": "A001"})
    rid = r.json()["report_id"]
    st = _wait(client, rid)
    assert st["status"] == "awaiting_review" and st["waiting_review"]
    rep = client.get(f"/reports/{rid}").json()
    assert rep["total_units"] == 53 and rep["body"]["boxes"]
    assert client.get(f"/reports/{rid}/photo").status_code == 200
    assert [p["report_id"] for p in client.get("/reviews/pending").json()] == [rid]
    assert client.post(f"/reports/{rid}/review", json={"action": "bogus"}).status_code == 400
    done = client.post(f"/reports/{rid}/review", json={"action": "approve", "reviewer": "sup"}).json()
    assert done["status"] == "approved"
    assert client.post(f"/reports/{rid}/review", json={"action": "approve"}).status_code == 409
    summ = client.get("/stores/00-0000001/summary").json()
    assert sum(r["front_facing_count"] for r in summ["rows"]) == 53


def test_retake_endpoint_and_limit(client):
    rid = client.post("/photos", files={"file": ("a.jpg", photo_bytes(seed=1), "image/jpeg")}, data={"store_code": "x"}).json()["report_id"]
    _wait(client, rid)
    assert client.post(f"/reports/{rid}/retake", files={"file": ("b.jpg", photo_bytes(seed=2), "image/jpeg")}).status_code == 200
    time.sleep(0.2)
    st = _wait(client, rid)
    assert st["retakes"] == 1
    assert client.post(f"/reports/{rid}/retake", files={"file": ("c.jpg", photo_bytes(seed=3), "image/jpeg")}).status_code == 409


def test_meta_endpoints(client):
    assert client.get("/health").json()["ok"]
    assert "validate_input" in client.get("/graph/mermaid").text
    stores = client.get("/stores", params={"route_code": "000000001"}).json()
    assert len(stores) == 3
    cat = client.get("/catalog", params={"q": "клубника"}).json()
    assert cat[0]["canon_name"] == "AI TEA клубника-киви"
    assert client.get("/catalog", params={"q": "вишня компотай"}).json()[0]["canon_name"] == "Компотай вишневый"
    assert client.get("/catalog", params={"q": "буратино дыня"}).json()[0]["canon_name"] == "Буратино дыня-мята"
    assert client.get("/reports/nope").status_code == 404


def test_agent_auth(client):
    assert client.post("/agents/auth", json={"phone": "8 (700) 000-00-01", "telegram_user_id": 42}).json()["agent_id"] == "A001"
    assert client.get("/agents/by-tg/42").json()["route_code"] == "000000001"
    assert client.post("/agents/auth", json={"phone": "+7 777 123 45 67", "telegram_user_id": 43}).status_code == 404
    assert client.get("/agents/by-tg/43").status_code == 404
    summ = client.get("/stores/00-0000001/summary").json()
    assert "detail" in summ
