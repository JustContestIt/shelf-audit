"""Retrieve reference images for an uncertain group: SigLIP ANN -> colour rerank (ensemble).

Score per canon name = z(max SigLIP sim over its refs) + z(max HSV sim over its refs),
z-normalised across the candidate canons of the query (as in the 24.08 experiment).
A group of N units is scored by the mean of its units' ensemble vectors.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from app.catalog import Ref
from app.rag.embed import SiglipEmbedder, hsv_feat
from app.rag.index import Hit, VectorIndex


@dataclass
class Candidate:
    canon_name: str
    score: float
    s_siglip: float
    s_hsv: float
    refs: list[Ref] = field(default_factory=list)  # best refs of this canon for the pass-2 prompt


@dataclass
class Retrieval:
    candidates: list[Candidate]
    n_crops: int
    backend: str  # "siglip+hsv" | "hsv"
    siglip_max: float | None = None  # mean over crops of the best SigLIP similarity to any ref of the brand

    @property
    def top1(self) -> str | None:
        return self.candidates[0].canon_name if self.candidates else None


def _z(v: np.ndarray) -> np.ndarray:
    return (v - v.mean()) / (v.std() + 1e-9)


def score_canons(hits: list[Hit], use_siglip: bool) -> dict[str, tuple[float, float, list[Hit]]]:
    per: dict[str, list[Hit]] = {}
    for h in hits:
        per.setdefault(h.ref.canon_name, []).append(h)
    return {c: (max(h.s_siglip for h in hs), max(h.s_hsv for h in hs), hs) for c, hs in per.items()}


def ensemble(canon_scores: dict[str, tuple[float, float, list[Hit]]], use_siglip: bool) -> dict[str, float]:
    names = list(canon_scores)
    if not names:
        return {}
    sig = np.array([canon_scores[c][0] for c in names])
    col = np.array([canon_scores[c][1] for c in names])
    tot = (_z(sig) if use_siglip else 0) + _z(col)
    return dict(zip(names, np.atleast_1d(tot).tolist(), strict=True))


class Retriever:
    def __init__(self, index: VectorIndex, siglip: SiglipEmbedder | None, *, stage1_limit: int = 64,
                 refs_per_canon: int = 2):
        self.index = index
        self.siglip = siglip
        self.stage1_limit = stage1_limit
        self.refs_per_canon = refs_per_canon

    @property
    def backend(self) -> str:
        return "siglip+hsv" if self.siglip is not None else "hsv"

    def retrieve(self, crops: list[Image.Image], *, brand: str | None = None, k: int = 3,
                 exclude_keys: list[str] | None = None) -> Retrieval:
        if not crops:
            return Retrieval([], 0, self.backend)
        sig = self.siglip.batch(crops) if self.siglip is not None else [None] * len(crops)
        acc: dict[str, list[float]] = {}
        best: dict[str, dict[str, Hit]] = {}
        raw: dict[str, list[tuple[float, float]]] = {}
        sig_max: list[float] = []
        for q_sig, crop in zip(sig, crops, strict=True):
            hits = self.index.search(q_sig, hsv_feat(crop), brand=brand, limit=self.stage1_limit, exclude_keys=exclude_keys)
            if self.siglip is not None and hits:
                sig_max.append(max(h.s_siglip for h in hits))
            cs = score_canons(hits, self.siglip is not None)
            ens = ensemble(cs, self.siglip is not None)
            for c, v in ens.items():
                acc.setdefault(c, []).append(v)
                raw.setdefault(c, []).append((cs[c][0], cs[c][1]))
                for h in cs[c][2]:
                    cur = best.setdefault(c, {}).get(h.ref.key)
                    if cur is None or h.s_siglip + h.s_hsv > cur.s_siglip + cur.s_hsv:
                        best[c][h.ref.key] = h
        n = len(crops)
        # canons missing for some crops get that crop's minimum (they were not even in stage 1)
        scored = []
        for c, vs in acc.items():
            pad = [min(min(v) for v in acc.values())] * (n - len(vs))
            scored.append((c, float(np.mean(vs + pad))))
        scored.sort(key=lambda t: -t[1])
        out = []
        for c, s in scored[:k]:
            hs = sorted(best[c].values(), key=lambda h: -(h.s_siglip + h.s_hsv))
            # prefer one field + one studio ref when available (field refs beat mockups, REPORT 24.08)
            field_first = sorted(hs, key=lambda h: h.ref.source != "field")
            picked = (field_first[:1] + [h for h in hs if h not in field_first[:1]])[: self.refs_per_canon]
            rs = raw[c]
            out.append(Candidate(c, s, float(np.mean([r[0] for r in rs])), float(np.mean([r[1] for r in rs])),
                                 [h.ref for h in picked]))
        return Retrieval(out, n, self.backend, float(np.mean(sig_max)) if sig_max else None)
