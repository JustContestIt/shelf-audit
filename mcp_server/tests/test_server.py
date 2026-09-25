"""MCP tools through a real MCP client (in-memory transport) against a mocked API."""
from __future__ import annotations

import json

import httpx
import pytest
from fastmcp import Client

import shelf_audit_mcp.server as srv

REPORT = {"report_id": "R_1", "status": "awaiting_review", "store_code": "00-0000001", "store_name": "Демо-точка 1",
          "body": {"report": {"total_units": 53, "needs_review_units": 2, "unknown_units": 0, "foreign_units": 5, "flags": [],
                              "cost_usd": 0.12, "rows": [{"shelf_index": 1, "brand": "AI TEA", "subtype": "AI TEA малина",
                                                          "package_format": "банка 0,45 л", "front_facing_count": 2,
                                                          "position": "центр", "needs_review": True,
                                                          "review_reason": "проход 2 не уверен"}]}}}
calls: list[str] = []


def handler(req: httpx.Request) -> httpx.Response:
    calls.append(f"{req.method} {req.url.path}")
    p = req.url.path
    if p == "/photos" and req.method == "POST":
        assert b"Content-Disposition" in req.content
        return httpx.Response(200, json={"report_id": "R_1", "status": "queued"})
    if p == "/photos/R_1/status":
        return httpx.Response(200, json={"status": "awaiting_review", "running": False})
    if p == "/reports/R_1":
        return httpx.Response(200, json=REPORT)
    if p == "/catalog":
        return httpx.Response(200, json=[{"key": "aitea_klubnika_kivi", "brand": "AI TEA", "canon_name": "AI TEA клубника-киви",
                                          "refs": 19}])
    if p == "/stores/00-0000001/summary":
        return httpx.Response(200, json={"store_code": "00-0000001", "rows": [{"brand": "AI TEA", "front_facing_count": 53}]})
    if p == "/reviews/pending":
        return httpx.Response(200, json=[{"report_id": "R_1", "status": "awaiting_review"}])
    return httpx.Response(404, json={"detail": "nope"})


@pytest.fixture(autouse=True)
def mock_api(monkeypatch):
    monkeypatch.setattr(srv, "_transport", httpx.MockTransport(handler))
    calls.clear()


async def test_tools_listed():
    async with Client(srv.mcp) as c:
        names = {t.name for t in await c.list_tools()}
    assert names == {"analyze_shelf_photo", "search_catalog", "get_store_report", "list_pending_reviews"}


async def test_analyze_photo(tmp_path):
    img = tmp_path / "shelf.jpg"
    img.write_bytes(b"\xff\xd8\xff fake jpeg")
    async with Client(srv.mcp) as c:
        res = await c.call_tool("analyze_shelf_photo", {"photo_path": str(img), "store_code": "00-0000001"})
    data = res.structured_content or json.loads(res.content[0].text)
    assert data["total_units"] == 53 and data["rows"][0]["needs_review"] is True
    assert data["review_url"].endswith("/reports/R_1")
    assert calls[:2] == ["POST /photos", "GET /photos/R_1/status"]


async def test_catalog_store_pending():
    async with Client(srv.mcp) as c:
        cat = await c.call_tool("search_catalog", {"query": "клубника"})
        rep = await c.call_tool("get_store_report", {"store_code": "00-0000001"})
        pend = await c.call_tool("list_pending_reviews", {})
    assert (cat.structured_content or {})["skus"][0]["canon_name"] == "AI TEA клубника-киви"
    assert (rep.structured_content or {})["total_units"] == 53
    assert "review_url" in json.dumps(pend.structured_content or pend.content[0].text)
