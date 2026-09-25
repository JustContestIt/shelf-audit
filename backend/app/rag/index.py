"""Vector store for reference images: pgvector in Postgres, numpy in memory for tests/offline.

Why pgvector and not Qdrant (ADR-006): 150–300 refs, ANN speed is irrelevant; one Postgres
already holds reports, LangGraph checkpoints and vectors — one container less.
Two vectors per ref: SigLIP (768, cosine, HNSW) and HSV histogram (96, cosine).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from app.catalog import Ref
from app.rag.embed import HSV_DIM, SIGLIP_DIM


@dataclass
class Hit:
    ref: Ref
    s_siglip: float
    s_hsv: float


class VectorIndex(Protocol):
    def upsert(self, refs: list[Ref], siglip: np.ndarray | None, hsv: np.ndarray) -> None: ...
    def search(self, q_siglip: np.ndarray | None, q_hsv: np.ndarray, *, brand: str | None = None,
               limit: int = 50, exclude_keys: list[str] | None = None) -> list[Hit]: ...
    def count(self) -> int: ...


def _excluded(key: str, exclude: list[str] | None) -> bool:
    return bool(exclude) and any(key == p or key.startswith(p + "__") for p in exclude)


class MemoryIndex:
    def __init__(self):
        self.refs: list[Ref] = []
        self.sig: np.ndarray | None = None
        self.hsv = np.zeros((0, HSV_DIM), np.float32)

    def upsert(self, refs, siglip, hsv):
        keys = {r.key for r in refs}
        keep = [i for i, r in enumerate(self.refs) if r.key not in keys]
        self.refs = [self.refs[i] for i in keep] + list(refs)
        self.hsv = np.concatenate([self.hsv[keep], hsv.astype(np.float32)])
        if siglip is not None:
            old = self.sig[keep] if self.sig is not None else np.zeros((0, SIGLIP_DIM), np.float32)
            self.sig = np.concatenate([old, siglip.astype(np.float32)])

    def search(self, q_siglip, q_hsv, *, brand=None, limit=50, exclude_keys=None):
        idx = [i for i, r in enumerate(self.refs) if (brand is None or r.brand == brand) and not _excluded(r.key, exclude_keys)]
        if not idx:
            return []
        s_h = self.hsv[idx] @ q_hsv
        s_s = self.sig[idx] @ q_siglip if (self.sig is not None and q_siglip is not None) else np.zeros(len(idx))
        order = np.argsort(-(s_s if q_siglip is not None else s_h))[:limit]
        return [Hit(self.refs[idx[o]], float(s_s[o]), float(s_h[o])) for o in order]

    def count(self):
        return len(self.refs)

    # persistence as .npz + .jsonl next to the catalog (offline mode, CI)
    def save(self, path: Path):
        np.savez_compressed(path, hsv=self.hsv, sig=self.sig if self.sig is not None else np.zeros((0, SIGLIP_DIM)))
        Path(str(path) + ".refs.jsonl").write_text("".join(json.dumps(r.to_json(), ensure_ascii=False) + "\n" for r in self.refs),
                                                   encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> MemoryIndex:
        m = cls()
        d = np.load(path)
        m.hsv = d["hsv"].astype(np.float32)
        m.sig = d["sig"].astype(np.float32) if d["sig"].size else None
        for line in Path(str(path) + ".refs.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                m.refs.append(Ref(**json.loads(line)))
        return m


DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS ref_embeddings (
  key        text PRIMARY KEY,
  brand      text NOT NULL,
  canon_name text NOT NULL,
  variant    text,
  pack       text,
  lang       text,
  source     text NOT NULL,
  path       text,
  meta       jsonb NOT NULL DEFAULT '{{}}',
  siglip     vector({SIGLIP_DIM}),
  hsv        vector({HSV_DIM}) NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ref_embeddings_siglip_hnsw ON ref_embeddings USING hnsw (siglip vector_cosine_ops);
CREATE INDEX IF NOT EXISTS ref_embeddings_brand ON ref_embeddings (brand);
"""


class PgVectorIndex:
    def __init__(self, dsn: str):
        import psycopg
        from pgvector.psycopg import register_vector

        self.dsn = dsn
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(DDL)
        self._register = register_vector

    def _conn(self):
        import psycopg

        c = psycopg.connect(self.dsn, autocommit=True)
        self._register(c)
        return c

    def upsert(self, refs, siglip, hsv):
        with self._conn() as c, c.cursor() as cur:
            for i, r in enumerate(refs):
                cur.execute(
                    """INSERT INTO ref_embeddings (key, brand, canon_name, variant, pack, lang, source, path, meta, siglip, hsv)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (key) DO UPDATE SET brand=EXCLUDED.brand, canon_name=EXCLUDED.canon_name,
                         variant=EXCLUDED.variant, pack=EXCLUDED.pack, lang=EXCLUDED.lang, source=EXCLUDED.source,
                         path=EXCLUDED.path, meta=EXCLUDED.meta, siglip=EXCLUDED.siglip, hsv=EXCLUDED.hsv, updated_at=now()""",
                    (r.key, r.brand, r.canon_name, r.variant, r.pack, r.lang, r.source, r.path,
                     json.dumps({"mime_type": r.mime_type, **(r.extra or {})}, ensure_ascii=False),
                     None if siglip is None else siglip[i].astype(np.float32), hsv[i].astype(np.float32)),
                )

    def search(self, q_siglip, q_hsv, *, brand=None, limit=50, exclude_keys=None):
        where, params = [], []
        if brand:
            where.append("brand = %s")
            params.append(brand)
        for p in exclude_keys or []:
            where.append("key <> %s AND key NOT LIKE %s")
            params += [p, p + "\\_\\_%"]
        w = ("WHERE " + " AND ".join(where)) if where else ""
        q_h = q_hsv.astype(np.float32)
        if q_siglip is not None:
            # stage 1: ANN on SigLIP (HNSW, cosine); similarities for the colour rerank come along
            sql = f"""SELECT key, brand, canon_name, variant, pack, lang, source, path, meta,
                             1 - (siglip <=> %s) AS s_sig, 1 - (hsv <=> %s) AS s_hsv
                      FROM ref_embeddings {w} ORDER BY siglip <=> %s LIMIT %s"""
            args = [q_siglip.astype(np.float32), q_h, *params, q_siglip.astype(np.float32), limit]
        else:
            sql = f"""SELECT key, brand, canon_name, variant, pack, lang, source, path, meta,
                             0.0 AS s_sig, 1 - (hsv <=> %s) AS s_hsv
                      FROM ref_embeddings {w} ORDER BY hsv <=> %s LIMIT %s"""
            args = [q_h, *params, q_h, limit]
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        hits = []
        for key, brand_, canon, variant, pack, lang, source, path, meta, s_sig, s_hsv in rows:
            meta = meta or {}
            ref = Ref(key=key, brand=brand_, canon_name=canon, variant=variant, pack=pack, lang=lang, source=source,
                      path=path, mime_type=meta.pop("mime_type", "image/jpeg"), extra=meta)
            hits.append(Hit(ref, float(s_sig), float(s_hsv)))
        return hits

    def count(self):
        with self._conn() as c:
            return c.execute("SELECT count(*) FROM ref_embeddings").fetchone()[0]
