"""Postgres-backed parts: PostgresSaver (resume after a restart), PgRepo, pgvector index.

Run with a database: DATABASE_URL=postgresql://postgres@localhost:5432/shelf pytest -m pg
(docker compose up postgres gives one). Skipped when DATABASE_URL is not set.
"""
from __future__ import annotations

import os
import uuid

import numpy as np
import pytest
from test_graph import ScriptedLLM, _detect_answer, _verify_answer, photo_bytes, run0644  # noqa: F401

from app.catalog import Ref
from app.config import Settings
from app.graph.deps import build_deps
from app.graph.state import Store
from app.rag.index import PgVectorIndex
from app.service import AuditService
from app.storage.repo import PgRepo

DSN = os.environ.get("DATABASE_URL")
pytestmark = [pytest.mark.pg, pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")]


def test_resume_after_restart_with_postgres_saver(tmp_path, run0644):  # noqa: F811
    s = Settings(photos_dir=tmp_path / "up", database_url=DSN, llm_mode="replay", replay_dir=tmp_path / "c",
                 catalog_path=tmp_path / "none.jsonl", data_dir=tmp_path)
    repo = PgRepo(DSN)
    mk = lambda: build_deps(s, repo=repo, retriever=None, detect_llm=ScriptedLLM("d", [_detect_answer(run0644)]),  # noqa: E731
                            verify_llm=ScriptedLLM("v", [_verify_answer(run0644)]))
    svc1 = AuditService(deps=mk(), settings=s)
    rid = svc1.submit(photo_bytes(), "a.jpg", Store(store_code="00-0000007", store_name="Демо-точка 7"), wait=True,
                      report_id="T_" + uuid.uuid4().hex[:8])
    assert repo.get_report(rid)["status"] == "awaiting_review"
    svc1.shutdown()
    # "restart": a new process state, same DB — the review button resumes the same thread
    svc2 = AuditService(deps=mk(), settings=s)
    assert svc2.state(rid)["waiting_review"]
    svc2.review(rid, {"action": "approve"})
    rec = repo.get_report(rid)
    assert rec["status"] == "approved" and rec["total_units"] == 53
    assert any(r["report_id"] == rid for r in repo.rows_for_export())


def test_pgvector_index_roundtrip():
    idx = PgVectorIndex(DSN)
    rng = np.random.default_rng(0)
    refs = [Ref(key=f"t_{i}__x", brand="AI TEA" if i % 2 else "Компотай", canon_name=f"C{i % 3}", source="studio", path=f"p{i}")
            for i in range(10)]
    sig = rng.normal(size=(10, 768)).astype(np.float32)
    sig /= np.linalg.norm(sig, axis=1, keepdims=True)
    hsv = np.abs(rng.normal(size=(10, 96))).astype(np.float32)
    hsv /= np.linalg.norm(hsv, axis=1, keepdims=True)
    idx.upsert(refs, sig, hsv)
    hits = idx.search(sig[3], hsv[3], brand="AI TEA", limit=3)
    assert hits[0].ref.key == "t_3__x" and abs(hits[0].s_siglip - 1) < 1e-4
    assert all(h.ref.brand == "AI TEA" for h in hits)
    assert not any(h.ref.key.startswith("t_3") for h in idx.search(sig[3], hsv[3], limit=10, exclude_keys=["t_3"]))
