"""Dependencies of the graph nodes (built once per process, injected into node closures)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.catalog import Ref, is_excluded, load_active_refs, load_catalog, sort_refs
from app.config import Settings, get_settings
from app.prompts import Prompt, load_prompt
from app.rag.retrieve import Retriever
from app.storage.repo import MemoryRepo, Repo
from app.vision.llm import VisionLLM, build_chain
from app.vision.postprocess import GeoParams
from app.vision.ref_parts import RefParts
from app.vision.requests import GenConfig


@dataclass
class Deps:
    settings: Settings
    detect_llm: VisionLLM
    verify_llm: VisionLLM
    repo: Repo
    ref_parts: RefParts
    retriever: Retriever | None = None
    guard_llm: VisionLLM | None = None
    geo: GeoParams = field(default_factory=GeoParams)

    @property
    def detect_prompt(self) -> Prompt:
        return load_prompt(self.settings.prompt_detect)

    @property
    def verify_prompt(self) -> Prompt:
        return load_prompt(self.settings.prompt_verify)

    def gen(self) -> GenConfig:
        s = self.settings
        return GenConfig(temperature=s.temperature, thinking_level=s.thinking_level, max_output_tokens=s.max_output_tokens,
                         top_p=s.top_p, media_resolution=s.media_resolution)

    def active_refs(self) -> list[Ref]:
        return sort_refs([r for r in load_active_refs(str(self.settings.active_refs_path))
                          if not is_excluded(r.key, self.settings.exclude_keys)])

    def catalog_refs(self) -> list[Ref]:
        return [r for r in load_catalog(str(self.settings.catalog_path)) if not is_excluded(r.key, self.settings.exclude_keys)]

    def cache_key(self, pass_name: str, photo_sha: str, **extra) -> str:
        """Key of the response cache: photo + prompt + refs + config (so re-scoring evals costs nothing)."""
        s = self.settings
        payload = {"pass": pass_name, "photo": photo_sha,
                   "prompt": (self.detect_prompt if pass_name == "detect" else self.verify_prompt).version,
                   "models": s.detect_models if pass_name == "detect" else s.verify_models,
                   "gen": self.gen().__dict__, "exclude": s.exclude_keys, "salt": s.cache_salt, **extra}
        return pass_name + "_" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
                                                .encode()).hexdigest()[:20]


def build_deps(settings: Settings | None = None, *, repo: Repo | None = None, retriever: Retriever | None = None,
               detect_llm: VisionLLM | None = None, verify_llm: VisionLLM | None = None) -> Deps:
    s = settings or get_settings()
    if repo is None:
        if s.database_url:
            from app.storage.repo import PgRepo

            repo = PgRepo(s.database_url)
        else:
            repo = MemoryRepo()
    if retriever is None:
        retriever = build_retriever(s)
    # replay never needs image bytes: refs are identified by key in the cache key
    mode = "key" if s.llm_mode == "replay" else "files_api" if s.gemini_api_key else "inline"
    return Deps(
        settings=s,
        detect_llm=detect_llm or build_chain(s.detect_models, s, pass_name="detect"),
        verify_llm=verify_llm or build_chain(s.verify_models, s, pass_name="verify"),
        repo=repo,
        ref_parts=RefParts(s.data_dir / "catalog", mode=mode, api_key=s.gemini_api_key, base_url=s.gemini_base_url),
        retriever=retriever,
    )


def build_retriever(s: Settings) -> Retriever | None:
    """pgvector if DATABASE_URL and the table is filled, else the .npz snapshot, else None (pass 2 uses all refs)."""
    from app.rag.embed import get_siglip
    from app.rag.index import MemoryIndex, PgVectorIndex

    siglip = get_siglip()
    backend = s.vector_backend
    if backend in ("pgvector", "auto") and s.database_url:
        try:
            idx = PgVectorIndex(s.database_url)
            if idx.count() > 0:
                return Retriever(idx, siglip)
        except Exception:  # noqa: BLE001 — DB down: fall back to the snapshot
            if backend == "pgvector":
                raise
    snap = Path(s.data_dir) / "catalog" / "index.npz"
    if backend in ("memory", "auto") and snap.exists():
        m = MemoryIndex.load(snap)
        return Retriever(m, siglip if m.sig is not None else None)
    return None
