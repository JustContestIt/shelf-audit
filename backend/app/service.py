"""AuditService: owns the compiled graph and runs photos through it (used by API, bot via API, MCP via API)."""
from __future__ import annotations

import logging
import secrets
import shutil
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from langgraph.types import Command

from app.config import Settings, get_settings
from app.graph.deps import Deps, build_deps
from app.graph.graph import build_graph, postgres_checkpointer, run_config
from app.graph.state import AuditState, Photo, Store

log = logging.getLogger("shelf-audit")


def new_report_id() -> str:
    return "R_" + time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)


class AuditService:
    def __init__(self, deps: Deps | None = None, settings: Settings | None = None, checkpointer=None, workers: int = 2):
        self.settings = settings or (deps.settings if deps else get_settings())
        self.deps = deps or build_deps(self.settings)
        if checkpointer is None and self.settings.database_url:
            checkpointer = postgres_checkpointer(self.settings.database_url)
        self.graph = build_graph(self.deps, checkpointer)
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="graph")
        self.jobs: dict[str, Future] = {}

    # ------------------------------------------------------------------ start / resume
    def save_photo(self, report_id: str, data: bytes, filename: str = "photo.jpg") -> Path:
        d = Path(self.settings.photos_dir) / report_id
        d.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower() or ".jpg"
        p = d / f"{int(time.time())}{suffix}"
        p.write_bytes(data)
        return p

    def submit(self, data: bytes | None, filename: str, store: Store, *, source: str = "api", frame_id: str | None = None,
               report_id: str | None = None, wait: bool = False, path: Path | None = None) -> str:
        """Start a run. `data` is saved under photos_dir; evals pass `path` of an existing file instead (no copy)."""
        rid = report_id or new_report_id()
        path = Path(path) if path is not None else self.save_photo(rid, data, filename)
        state = AuditState(report_id=rid, photo=Photo(path=str(path), source=source, frame_id=frame_id), store=store,
                           config_id=self.settings.config_id)
        cfg = run_config(self.deps, rid, [f"source:{source}"])
        # visible immediately (status "queued") even before a worker picks the job up
        self.deps.repo.upsert_report({"report_id": rid, "status": "queued", "store_code": store.store_code,
                                      "store_name": store.store_name, "route_code": store.route_code,
                                      "agent_id": store.agent_id, "source": source, "photo_path": str(path),
                                      "config_id": self.settings.config_id, "flags": [], "body": {}})
        fut = self.pool.submit(self._run, rid, state, cfg)
        self.jobs[rid] = fut
        if wait:
            fut.result()
        return rid

    def submit_path(self, path: Path, store: Store, *, copy: bool = True, **kw) -> str:
        if copy:
            return self.submit(Path(path).read_bytes(), Path(path).name, store, **kw)
        return self.submit(None, Path(path).name, store, path=Path(path), **kw)

    def _run(self, rid: str, inp, cfg):
        try:
            self.graph.invoke(inp, cfg)
        except Exception as e:  # noqa: BLE001 — a crash must be visible in the report, not only in logs
            log.exception("graph failed for %s", rid)
            self.deps.repo.upsert_report({"report_id": rid, "status": "failed", "reject_reason": f"{type(e).__name__}: {e}"[:500],
                                          "flags": ["crash"], "body": {}})
            raise

    def review(self, rid: str, decision: dict, *, wait: bool = True) -> Future:
        cfg = run_config(self.deps, rid, ["review"])
        fut = self.pool.submit(self._run, rid, Command(resume=decision), cfg)
        self.jobs[rid] = fut
        if wait:
            fut.result()
        return fut

    def retake(self, rid: str, data: bytes, filename: str, *, wait: bool = False) -> None:
        path = self.save_photo(rid, data, filename)
        self.review(rid, {"action": "retake", "photo_path": str(path)}, wait=wait)

    # ------------------------------------------------------------------ read
    def state(self, rid: str) -> dict | None:
        snap = self.graph.get_state(run_config(self.deps, rid))
        if not snap or not snap.values:
            return None
        v = snap.values
        st = v if isinstance(v, dict) else v.model_dump()
        waiting = bool(snap.tasks and any(t.interrupts for t in snap.tasks))
        job = self.jobs.get(rid)
        return {
            "report_id": rid,
            "status": st.get("status"),
            "running": bool(job and not job.done()),
            "waiting_review": waiting,
            "next": list(snap.next or ()),
            "reject_reason": st.get("reject_reason"),
            "progress": [p if isinstance(p, dict) else p.model_dump() for p in st.get("progress", [])],
            "retakes": st.get("retakes", 0),
        }

    def wait(self, rid: str, timeout: float | None = None) -> None:
        f = self.jobs.get(rid)
        if f:
            f.result(timeout=timeout)

    def shutdown(self):
        self.pool.shutdown(wait=True)

    def delete_photos(self, rid: str):
        shutil.rmtree(Path(self.settings.photos_dir) / rid, ignore_errors=True)
