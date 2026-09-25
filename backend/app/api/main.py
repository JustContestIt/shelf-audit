"""FastAPI: the only door to the graph. Web cabinet, Telegram bot and MCP server all call it.

POST /photos                  start a run (multipart photo + store) -> report_id
GET  /photos/{id}/status      progress by graph nodes (polling from the cabinet / bot)
GET  /reports                 list (filters: store_code, status)
GET  /reports/{id}            report + boxes for the review screen
GET  /reports/{id}/photo      the photo (for box overlay)
POST /reports/{id}/review     approve | edit -> resume the interrupted thread
POST /reports/{id}/retake     new photo -> resume with "переснять" (loops back to validate_input)
GET  /reviews/pending         queue of reports waiting for a supervisor
GET  /stores, /stores/{code}/summary
GET  /catalog, POST /catalog/search-image
GET  /evals/latest            last eval results for the cabinet page
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app import __version__
from app.catalog import SKUS, load_catalog
from app.config import REPO_ROOT, get_settings
from app.graph.state import Store
from app.service import AuditService

log = logging.getLogger("shelf-audit.api")
_service: AuditService | None = None


def service() -> AuditService:
    global _service
    if _service is None:
        _service = AuditService()
        _seed_demo_routes(_service)
    return _service


def _seed_demo_routes(svc: AuditService):
    """Demo route sheet (the real one comes from the customer's system export)."""
    seed = REPO_ROOT / "backend" / "app" / "storage" / "demo_seed.json"
    if seed.exists() and hasattr(svc.deps.repo, "seed"):
        d = json.loads(seed.read_text(encoding="utf-8"))
        svc.deps.repo.seed(d.get("stores", []), d.get("agents", []))


@asynccontextmanager
async def lifespan(app: FastAPI):
    service()
    yield
    if _service:
        _service.shutdown()


app = FastAPI(title="shelf-audit API", version=__version__, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"])


def auth(authorization: str | None = Header(default=None)):
    token = get_settings().api_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(401, "bad token")


# ------------------------------------------------------------------ photos
@app.post("/photos", dependencies=[Depends(auth)])
async def post_photo(file: UploadFile = File(...), store_code: str = Form(""), store_name: str = Form(""),
                     route_code: str = Form(""), agent_id: str = Form(""), chat_id: str | None = Form(None),
                     source: str = Form("api"), frame_id: str | None = Form(None)):
    data = await file.read()
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "photo too large")
    rid = service().submit(data, file.filename or "photo.jpg",
                           Store(store_code=store_code, store_name=store_name, route_code=route_code, agent_id=agent_id,
                                 chat_id=chat_id), source=source, frame_id=frame_id)
    return {"report_id": rid, "status": "queued"}


@app.get("/photos/{rid}/status", dependencies=[Depends(auth)])
def photo_status(rid: str):
    st = service().state(rid)
    if st is None:
        rec = service().deps.repo.get_report(rid)
        if rec is None:
            raise HTTPException(404, "unknown report")
        job = service().jobs.get(rid)
        return {"report_id": rid, "status": rec["status"], "running": bool(job and not job.done()), "waiting_review": False,
                "next": [], "progress": [], "reject_reason": rec.get("reject_reason"), "retakes": 0}
    return st


# ------------------------------------------------------------------ reports
def _brief(rec: dict) -> dict:
    keys = ("report_id", "created_at", "updated_at", "status", "store_code", "store_name", "route_code", "agent_id", "source",
            "total_units", "unknown_units", "needs_review_units", "overall_confidence", "low_confidence", "cost_usd",
            "latency_s", "prompt_version", "models", "reject_reason", "flags")
    return {k: rec.get(k) for k in keys}


@app.get("/reports", dependencies=[Depends(auth)])
def list_reports(store_code: str | None = None, status: str | None = None, limit: int = Query(50, le=500)):
    return [_brief(r) for r in service().deps.repo.list_reports(store_code=store_code, status=status, limit=limit)]


@app.get("/reports/{rid}", dependencies=[Depends(auth)])
def get_report(rid: str):
    rec = service().deps.repo.get_report(rid)
    if rec is None:
        raise HTTPException(404, "unknown report")
    return {**_brief(rec), "review": rec.get("review"), "body": rec.get("body") or {}}


@app.get("/reports/{rid}/photo")
def get_photo(rid: str):
    rec = service().deps.repo.get_report(rid)
    if rec is None or not rec.get("photo_path") or not Path(rec["photo_path"]).exists():
        raise HTTPException(404, "no photo")
    return FileResponse(rec["photo_path"])


class ReviewIn(BaseModel):
    action: str  # approve | edit
    edits: list[dict] = []
    reviewer: str | None = None
    comment: str | None = None


@app.post("/reports/{rid}/review", dependencies=[Depends(auth)])
def review(rid: str, body: ReviewIn):
    if body.action not in ("approve", "edit"):
        raise HTTPException(400, "action must be approve | edit (retake: POST /reports/{id}/retake with a photo)")
    st = service().state(rid)
    if not st or not st.get("waiting_review"):
        raise HTTPException(409, "report is not waiting for review")
    service().review(rid, body.model_dump(), wait=True)
    return get_report(rid)


@app.post("/reports/{rid}/retake", dependencies=[Depends(auth)])
async def retake(rid: str, file: UploadFile = File(...)):
    st = service().state(rid)
    if not st or not st.get("waiting_review"):
        raise HTTPException(409, "report is not waiting for review")
    if st.get("retakes", 0) >= get_settings().max_retakes:
        raise HTTPException(409, f"пересъёмка уже была ({st['retakes']}); утвердите или исправьте отчёт")
    service().retake(rid, await file.read(), file.filename or "retake.jpg", wait=False)
    return {"report_id": rid, "status": "queued"}


@app.get("/reviews/pending", dependencies=[Depends(auth)])
def pending(store_code: str | None = None, limit: int = 100):
    return [_brief(r) for r in service().deps.repo.list_reports(store_code=store_code, status="awaiting_review", limit=limit)]


# ------------------------------------------------------------------ stores / summary
@app.get("/stores", dependencies=[Depends(auth)])
def stores(route_code: str | None = None):
    return service().deps.repo.stores_for_route(route_code)


@app.get("/stores/{store_code}/summary", dependencies=[Depends(auth)])
def store_summary(store_code: str, day: date | None = None, include_pending: bool = False):
    """Aggregated facings per (brand, subtype, format) for a store — what the Skill turns into xlsx."""
    recs = service().deps.repo.list_reports(store_code=store_code, limit=500)
    ok_status = {"approved", "edited"} | ({"awaiting_review"} if include_pending else set())
    recs = [r for r in recs if r["status"] in ok_status and (day is None or str(r["created_at"])[:10] == day.isoformat())]
    agg: dict[tuple, dict] = {}
    detail = []
    for r in recs:
        for row in ((r.get("body") or {}).get("report") or {}).get("rows", []):
            detail.append({"report_id": r["report_id"], "report_date": str(r["created_at"])[:19], "route_code": r.get("route_code", ""),
                           "store_code": r.get("store_code", ""), "store_name": r.get("store_name", ""),
                           "agent_id": r.get("agent_id", ""), "status": r["status"], "shelf_index": row["shelf_index"],
                           "position": row.get("position"), "brand": row["brand"], "subtype": row.get("subtype"),
                           "package_format": row.get("package_format"), "front_facing_count": row["front_facing_count"],
                           "needs_review": bool(row.get("needs_review")), "review_reason": row.get("review_reason")})
            k = (row["brand"], row.get("subtype"), row.get("package_format"))
            a = agg.setdefault(k, {"brand": k[0], "subtype": k[1], "package_format": k[2], "front_facing_count": 0,
                                   "needs_review_count": 0, "reports": set()})
            a["front_facing_count"] += row["front_facing_count"]
            a["needs_review_count"] += row["front_facing_count"] if row.get("needs_review") else 0
            a["reports"].add(r["report_id"])
    rows = sorted(({**a, "reports": sorted(a["reports"])} for a in agg.values()),
                  key=lambda a: (a["brand"], a["subtype"] or "", a["package_format"] or ""))
    return {"store_code": store_code, "day": day.isoformat() if day else None, "reports": [_brief(r) for r in recs],
            "rows": rows, "detail": detail}


# ------------------------------------------------------------------ agents (bot auth, simplified)
class AgentAuthIn(BaseModel):
    phone: str
    telegram_user_id: int
    verified_contact: bool = True  # False = typed by hand (logged as unconfirmed, BACKLOG №3)


@app.post("/agents/auth", dependencies=[Depends(auth)])
def agent_auth(body: AgentAuthIn):
    repo = service().deps.repo
    agent = repo.agent_by_phone(body.phone)
    if agent is None:
        raise HTTPException(404, "номер не найден в списке агентов")
    repo.bind_agent_tg(agent["agent_id"], body.telegram_user_id)
    log.info("agent %s bound to tg %s (contact verified: %s)", agent["agent_id"], body.telegram_user_id, body.verified_contact)
    return {k: agent.get(k) for k in ("agent_id", "name", "route_code", "role")}


@app.get("/agents/by-tg/{tg_id}", dependencies=[Depends(auth)])
def agent_by_tg(tg_id: int):
    agent = service().deps.repo.agent_by_tg(tg_id)
    if agent is None:
        raise HTTPException(404, "not registered")
    return {k: agent.get(k) for k in ("agent_id", "name", "route_code", "role")}


# ------------------------------------------------------------------ catalog
@app.get("/catalog", dependencies=[Depends(auth)])
def catalog(q: str | None = None, brand: str | None = None, limit: int = 50):
    import difflib

    skus = [{"key": k, "brand": b, "canon_name": c, "label_bg": col} for k, (b, c, col) in SKUS.items()]
    if brand:
        skus = [s for s in skus if s["brand"].lower() == brand.lower()]
    if q:
        def toks(x: str) -> list[str]:
            return [t for t in x.lower().replace("ё", "е").replace("-", " ").split() if t]

        qt = toks(q)

        def score(name: str) -> float:  # stem match per query word (вишня ~ вишневый) + fuzzy tie-break
            nt = toks(name)
            hits = sum(any(n.startswith(t[:4]) or t.startswith(n[:4]) for n in nt) for t in qt) / max(1, len(qt))
            return hits + 0.2 * difflib.SequenceMatcher(None, " ".join(qt), " ".join(nt)).ratio()

        skus = sorted(skus, key=lambda sk: -score(sk["canon_name"]))
    refs = load_catalog(str(get_settings().catalog_path))
    counts: dict[str, int] = {}
    for r in refs:
        counts[r.canon_name] = counts.get(r.canon_name, 0) + 1
    return [{**s, "refs": counts.get(s["canon_name"], 0)} for s in skus[:limit]]


@app.post("/catalog/search-image", dependencies=[Depends(auth)])
async def search_image(file: UploadFile = File(...), brand: str | None = Form(None), k: int = Form(5)):
    retr = service().deps.retriever
    if retr is None:
        raise HTTPException(503, "reference index is not built (make index)")
    from app.vision.crops import load_image

    r = retr.retrieve([load_image(await file.read())], brand=brand, k=k, exclude_keys=get_settings().exclude_keys)
    return {"backend": r.backend, "candidates": [{"canon_name": c.canon_name, "score": round(c.score, 3),
                                                  "refs": [x.key for x in c.refs]} for c in r.candidates]}


# ------------------------------------------------------------------ evals / meta
@app.get("/evals/latest")
def evals_latest():
    d = REPO_ROOT / "evals" / "results"
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if d.exists() else []
    return [json.loads(p.read_text(encoding="utf-8")) | {"file": p.name} for p in files[:20]]


@app.get("/graph/mermaid", response_class=PlainTextResponse)
def graph_mermaid():
    return service().graph.get_graph().draw_mermaid()


@app.get("/health")
def health():
    s = get_settings()
    svc = service()
    return {"ok": True, "version": __version__, "llm_mode": s.llm_mode, "gemini_key": bool(s.gemini_api_key),
            "db": bool(s.database_url), "retriever": svc.deps.retriever.backend if svc.deps.retriever else None,
            "refs_indexed": svc.deps.retriever.index.count() if svc.deps.retriever else 0,
            "prompt": svc.deps.detect_prompt.version, "verify_prompt": svc.deps.verify_prompt.version}
