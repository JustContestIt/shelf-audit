"""shelf-audit-mcp — one contract for three clients: the web cabinet assistant, Claude Desktop /
Claude Code analytics, and the `shelf-audit-report` Skill.

Tools (all go through the same FastAPI as the cabinet and the bot — no second copy of the logic):
  analyze_shelf_photo   run the audit graph on a photo and wait for the report (stops at human review)
  search_catalog        find SKUs by text, or reference images by a photo (visual RAG)
  get_store_report      aggregated facings of a store (approved reports; optionally pending ones)
  list_pending_reviews  reports waiting for a supervisor

Run:
  shelf-audit-mcp                                  # stdio (Claude Desktop / Claude Code)
  shelf-audit-mcp --transport http --port 8765     # streamable HTTP (docker compose service "mcp")
Env: API_BASE_URL (default http://localhost:8000), API_TOKEN (optional), CABINET_URL (links in answers).
"""
from __future__ import annotations

import argparse
import base64
import os
import time
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastmcp import FastMCP
from pydantic import Field

API = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
CABINET = os.environ.get("CABINET_URL", "http://localhost:8080").rstrip("/")
TERMINAL = {"awaiting_review", "approved", "edited", "rejected", "failed"}

mcp = FastMCP(
    name="shelf-audit-mcp",
    instructions=(
        "Shelf audit of drinks (brands Буратино, AI TEA, Chino, Компотай, Tamga) from shelf photos. "
        "Counts are front-row facings per shelf; competitors (ЧУЖОЙ) are never counted. Rows with needs_review "
        "are not final — report them separately. Photos run 1–2 minutes (two Gemini passes)."
    ),
)
_transport: httpx.BaseTransport | None = None  # tests inject httpx.MockTransport


def _client() -> httpx.Client:
    headers = {"Authorization": f"Bearer {os.environ['API_TOKEN']}"} if os.environ.get("API_TOKEN") else {}
    return httpx.Client(base_url=API, headers=headers, timeout=60, transport=_transport)


def _brief_report(rep: dict) -> dict:
    body = rep.get("body") or {}
    r = body.get("report") or {}
    rows = r.get("rows") or []
    return {
        "report_id": rep.get("report_id"),
        "status": rep.get("status"),
        "store": {"code": rep.get("store_code"), "name": rep.get("store_name")},
        "total_units": r.get("total_units"),
        "needs_review_units": r.get("needs_review_units"),
        "unknown_units": r.get("unknown_units"),
        "foreign_units_not_counted": r.get("foreign_units"),
        "rows": [{"shelf": x["shelf_index"], "brand": x["brand"], "subtype": x.get("subtype"), "pack": x.get("package_format"),
                  "count": x["front_facing_count"], "position": x.get("position"), "needs_review": x.get("needs_review"),
                  "review_reason": x.get("review_reason")} for x in rows],
        "flags": r.get("flags") or rep.get("flags") or [],
        "cost_usd": r.get("cost_usd"),
        "reject_reason": rep.get("reject_reason"),
        "review_url": f"{CABINET}/reports/{rep.get('report_id')}",
    }


@mcp.tool(annotations={"title": "Analyze a shelf photo", "readOnlyHint": False, "openWorldHint": False})
def analyze_shelf_photo(
    photo_path: Annotated[str | None, Field(description="Path to a JPEG/PNG/HEIC file readable by this server")] = None,
    photo_base64: Annotated[str | None, Field(description="The photo as base64 (alternative to photo_path)")] = None,
    store_code: Annotated[str, Field(description="Store code from the route sheet, e.g. 00-0000001")] = "",
    store_name: Annotated[str, Field(description="Store name for the report")] = "",
    agent_id: Annotated[str, Field(description="Agent id (for the customer report)")] = "mcp",
    wait_seconds: Annotated[int, Field(ge=0, le=600, description="How long to wait for the result; 0 = return at once")] = 240,
) -> dict[str, Any]:
    """Run the shelf-audit graph on one photo: detection -> counts -> subtype check -> report.
    The graph stops at human review: the report is returned with status awaiting_review and a link
    to the review screen. Units marked needs_review are not final."""
    if photo_path:
        p = Path(photo_path).expanduser()
        data, name = p.read_bytes(), p.name
    elif photo_base64:
        data, name = base64.b64decode(photo_base64), "photo.jpg"
    else:
        raise ValueError("give photo_path or photo_base64")
    with _client() as c:
        r = c.post("/photos", files={"file": (name, data)},
                   data={"store_code": store_code, "store_name": store_name, "agent_id": agent_id, "source": "mcp"})
        r.raise_for_status()
        rid = r.json()["report_id"]
        t0 = time.time()
        status = "queued"
        while wait_seconds and time.time() - t0 < wait_seconds:
            st = c.get(f"/photos/{rid}/status").json()
            status = st.get("status")
            if status in TERMINAL and not st.get("running"):
                break
            time.sleep(2)
        if status not in TERMINAL:
            return {"report_id": rid, "status": status, "message": "still running — call get_report later",
                    "review_url": f"{CABINET}/reports/{rid}"}
        return _brief_report(c.get(f"/reports/{rid}").json())


@mcp.tool(annotations={"title": "Search the SKU catalog", "readOnlyHint": True})
def search_catalog(
    query: Annotated[str | None, Field(description="Text: brand / flavour / pack, e.g. 'клубника', 'компотай вишня'")] = None,
    image_path: Annotated[str | None, Field(description="Or a crop of one product to find the closest reference images")] = None,
    brand: Annotated[str | None, Field(description="Restrict to a brand: Буратино | AI TEA | Chino | Компотай | Tamga")] = None,
    k: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict[str, Any]:
    """Find catalog SKUs by text (fuzzy over canon names) or by an image (SigLIP + colour histogram
    over the reference images, the same retriever pass 2 uses)."""
    with _client() as c:
        if image_path:
            p = Path(image_path).expanduser()
            r = c.post("/catalog/search-image", files={"file": (p.name, p.read_bytes())},
                       data={"k": str(k), **({"brand": brand} if brand else {})})
            r.raise_for_status()
            return {"by": "image", **r.json()}
        params: dict[str, Any] = {"limit": k}
        if query:
            params["q"] = query
        if brand:
            params["brand"] = brand
        r = c.get("/catalog", params=params)
        r.raise_for_status()
        return {"by": "text", "skus": r.json()}


@mcp.tool(annotations={"title": "Store report", "readOnlyHint": True})
def get_store_report(
    store_code: Annotated[str, Field(description="Store code, e.g. 00-0000001")],
    day: Annotated[str | None, Field(description="YYYY-MM-DD; empty = all days")] = None,
    include_pending: Annotated[bool, Field(description="Also count reports not yet approved (marked as such)")] = False,
) -> dict[str, Any]:
    """Facings of a store aggregated by brand, subtype and pack from approved/edited reports.
    needs_review_count shows how many of the units still need a supervisor's check."""
    with _client() as c:
        params: dict[str, Any] = {"include_pending": str(include_pending).lower()}
        if day:
            params["day"] = day
        r = c.get(f"/stores/{store_code}/summary", params=params)
        r.raise_for_status()
        out = r.json()
        out["total_units"] = sum(x["front_facing_count"] for x in out.get("rows", []))
        return out


@mcp.tool(annotations={"title": "Pending reviews", "readOnlyHint": True})
def list_pending_reviews(
    store_code: Annotated[str | None, Field(description="Filter by store code")] = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 20,
) -> list[dict[str, Any]]:
    """Reports waiting for a supervisor (status awaiting_review), newest first, with review links."""
    with _client() as c:
        params: dict[str, Any] = {"limit": limit}
        if store_code:
            params["store_code"] = store_code
        r = c.get("/reviews/pending", params=params)
        r.raise_for_status()
        return [{**x, "review_url": f"{CABINET}/reports/{x['report_id']}"} for x in r.json()]


def main() -> None:
    ap = argparse.ArgumentParser(description="shelf-audit MCP server")
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.transport == "stdio":
        mcp.run(transport="stdio", show_banner=False)
    else:
        mcp.run(transport="http", host=a.host, port=a.port, show_banner=False)


if __name__ == "__main__":
    main()
