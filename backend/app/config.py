"""Runtime settings. Everything comes from env / .env; nothing secret has a default."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), extra="ignore")

    # --- LLM ---------------------------------------------------------------
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    # fallback chain for pass 1 / pass 2, first = primary (ADR-005)
    detect_models: list[str] = ["gemini-3.5-flash", "gemini-3-flash-preview"]
    verify_models: list[str] = ["gemini-3.5-flash", "gemini-3-flash-preview"]
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None  # e.g. "openai/gpt-5.6"; empty = OpenRouter not in the chain
    llm_timeout_s: float = 120.0
    llm_max_retries: int = 3
    temperature: float = 0.0
    thinking_level: str | None = None  # None = model default; "low" | "high"
    max_output_tokens: int | None = None
    top_p: float | None = None  # None = model default (not sent)
    media_resolution: str | None = "MEDIA_RESOLUTION_ULTRA_HIGH"  # per-part on the target photo only
    # replay: answer from recorded responses instead of calling the API (tests, evals, demo without key)
    llm_mode: str = "live"  # "live" | "replay" | "record"
    replay_dir: Path = REPO_ROOT / "evals" / "cache"

    # --- pipeline ----------------------------------------------------------
    prompt_detect: str = "detect_v7.5"
    prompt_verify: str = "verify_v9"
    exclude_keys: list[str] = ["aitea_reven"]  # 31.08: SKU excluded from enum and refs (see DECISIONS ADR-009)
    pass2_mode: str = "gate"  # "always" | "gate" | "check" (RAG ours/foreign check, no LLM pass 2) | "off"
    pass2_refs: str = "topk"  # "topk" (RAG) | "all" (46 refs as in n8n) — A/B-1
    rag_top_k: int = 3
    max_verify_iterations: int = 2
    max_retakes: int = 1
    low_confidence_threshold: float = 0.8
    # ours/foreign check on unnamed groups (REPORT 24.08: SigLIP max-sim < 0.70 lets 3% of foreign through)
    foreign_check: bool = True
    foreign_sim_threshold: float = 0.70
    foreign_action: str = "exclude"  # "exclude" (out of the count until a supervisor restores) | "flag"
    config_id: str = "default"
    cache_salt: str = ""  # evals: a different salt per repeat, so repeats are separate recorded answers

    # --- data --------------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"
    photos_dir: Path = REPO_ROOT / "data" / "uploads"
    catalog_path: Path = REPO_ROOT / "data" / "catalog" / "catalog.jsonl"
    active_refs_path: Path = REPO_ROOT / "backend" / "app" / "catalog" / "active_refs.yaml"
    siglip_onnx: Path = REPO_ROOT / "data" / "models" / "siglip_vision.onnx"

    # --- storage -----------------------------------------------------------
    database_url: str | None = None  # postgresql://user:pass@host:5432/db ; None = in-memory (dev/tests)
    vector_backend: str = "auto"  # "pgvector" | "memory" | "auto"

    # --- observability -----------------------------------------------------
    langsmith_tracing: bool = False
    langsmith_project: str = "shelf-audit"

    # --- guardrails --------------------------------------------------------
    min_side_px: int = 640
    max_upload_mb: int = 20
    blur_threshold: float = 60.0  # variance of Laplacian on 1024px grayscale
    shelf_check_llm: bool = False  # extra cheap LLM call "is this a shelf?" before pass 1

    # --- api / bot ----------------------------------------------------------
    api_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])
    api_token: str | None = None  # simple shared token for bot/mcp -> api; None = open (dev)


@lru_cache
def get_settings() -> Settings:
    return Settings()
