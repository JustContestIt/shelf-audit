"""LLM clients for the vision passes.

* GeminiClient — REST generateContent with the exact body n8n sent (ADR-004: body parity with
  production; the google-genai SDK can replace it behind the same interface).
  Retries on 429/500/503 with exponential backoff, timeout, usage -> USD.
* OpenRouterClient — OpenAI-compatible fallback (e.g. GPT-5.6 via OpenRouter); converts parts.
* ReplayClient — answers from recorded responses (evals cache, n8n runs). Used by tests, by
  `make eval` without a key, and as the demo safety net against 429 (DEMO_CHECKLIST 31.08).
* FallbackChain — tries clients in order; records which one answered.

All calls go through `call_llm` so LangSmith sees them as LLM runs with tokens and cost.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

try:
    from langsmith import traceable
except Exception:  # pragma: no cover - langsmith is a hard dependency, keep import-safe anyway
    def traceable(*a, **k):
        return (lambda f: f) if not a or not callable(a[0]) else a[0]

# USD per 1M tokens (ai.google.dev/gemini-api/docs/pricing, checked 25.09.2026). Override in configs.
PRICES: dict[str, dict[str, float]] = {
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00, "cached": 0.15},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00, "cached": 0.05},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50, "cached": 0.025},
}
RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None, retryable: bool = False):
        super().__init__(msg)
        self.status = status
        self.retryable = retryable


@dataclass
class LLMResult:
    raw: dict                     # Gemini-shaped response: candidates[0].content.parts[].text + usageMetadata
    model: str
    provider: str
    latency_s: float
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None
    attempts: int = 1
    replayed: bool = False
    fallback_from: list[str] = field(default_factory=list)


class VisionLLM(Protocol):
    name: str

    def generate(self, body: dict, *, cache_key: str | None = None) -> LLMResult: ...


def usage_from_raw(raw: dict) -> dict:
    u = raw.get("usageMetadata") or {}
    return {"input_tokens": u.get("promptTokenCount") or 0, "output_tokens": (u.get("candidatesTokenCount") or 0)
            + (u.get("thoughtsTokenCount") or 0), "cached_tokens": u.get("cachedContentTokenCount") or 0,
            "thoughts_tokens": u.get("thoughtsTokenCount") or 0}


def cost_usd(model: str, usage: dict) -> float | None:
    p = PRICES.get(model)
    if not p:
        return None
    cached = usage.get("cached_tokens") or 0
    fresh = max(0, (usage.get("input_tokens") or 0) - cached)
    return round((fresh * p["input"] + cached * p["cached"] + (usage.get("output_tokens") or 0) * p["output"]) / 1e6, 6)


def body_fingerprint(body: dict, model: str | None = None) -> str:
    """Stable hash of (photo + prompt + refs + config) — key of the evals response cache."""
    h = hashlib.sha256()
    h.update((model or "").encode())
    h.update(json.dumps(body, ensure_ascii=False, sort_keys=True).encode())
    return h.hexdigest()[:24]


# ------------------------------------------------------------------ Gemini REST
class GeminiClient:
    provider = "google"

    def __init__(self, model: str, api_key: str, base_url: str = "https://generativelanguage.googleapis.com/v1beta",
                 timeout: float = 120.0, max_retries: int = 3, backoff: float = 5.0, transport: httpx.BaseTransport | None = None):
        self.name = model
        self.model = model
        self.url = f"{base_url}/models/{model}:generateContent"
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def generate(self, body: dict, *, cache_key: str | None = None) -> LLMResult:
        t0 = time.monotonic()
        last: LLMError | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self._client.post(self.url, json=body, headers={"x-goog-api-key": self.api_key})
            except httpx.TimeoutException:
                last = LLMError(f"{self.model}: timeout {self.timeout}s", None, True)
            except httpx.HTTPError as e:
                last = LLMError(f"{self.model}: {type(e).__name__}", None, True)
            else:
                if r.status_code == 200:
                    raw = r.json()
                    usage = usage_from_raw(raw)
                    return LLMResult(raw, self.model, self.provider, time.monotonic() - t0, usage, cost_usd(self.model, usage), attempt)
                retryable = r.status_code in RETRY_STATUS
                last = LLMError(f"{self.model}: HTTP {r.status_code} {r.text[:300]}", r.status_code, retryable)
                if not retryable:
                    raise last
            if attempt < self.max_retries:
                time.sleep(self.backoff * (2 ** (attempt - 1)))
        raise last or LLMError(f"{self.model}: failed")


# ------------------------------------------------------------------ OpenRouter (OpenAI-compatible)
class OpenRouterClient:
    provider = "openrouter"

    def __init__(self, model: str, api_key: str, timeout: float = 180.0, transport: httpx.BaseTransport | None = None):
        self.name = f"openrouter:{model}"
        self.model = model
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout, transport=transport)

    @staticmethod
    def to_openai(body: dict) -> dict:
        content = []
        for p in body["contents"][0]["parts"]:
            if "text" in p:
                content.append({"type": "text", "text": p["text"]})
            elif "inline_data" in p:
                d = p["inline_data"]
                content.append({"type": "image_url", "image_url": {"url": f"data:{d['mime_type']};base64,{d['data']}"}})
            elif "file_data" in p:
                content.append({"type": "image_url", "image_url": {"url": p["file_data"]["file_uri"]}})
        gc = body.get("generationConfig", {})
        return {
            "messages": [{"role": "system", "content": body["systemInstruction"]["parts"][0]["text"]},
                         {"role": "user", "content": content}],
            "temperature": gc.get("temperature", 0),
            "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": _openai_schema(gc["response_schema"])}},
        }

    def generate(self, body: dict, *, cache_key: str | None = None) -> LLMResult:
        t0 = time.monotonic()
        payload = {"model": self.model, **self.to_openai(body)}
        r = self._client.post("https://openrouter.ai/api/v1/chat/completions", json=payload,
                              headers={"Authorization": f"Bearer {self.api_key}"})
        if r.status_code != 200:
            raise LLMError(f"{self.name}: HTTP {r.status_code} {r.text[:300]}", r.status_code, r.status_code in RETRY_STATUS)
        j = r.json()
        text = j["choices"][0]["message"]["content"]
        u = j.get("usage") or {}
        raw = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": j["choices"][0].get("finish_reason")}],
               "usageMetadata": {"promptTokenCount": u.get("prompt_tokens"), "candidatesTokenCount": u.get("completion_tokens")}}
        usage = usage_from_raw(raw)
        return LLMResult(raw, self.model, self.provider, time.monotonic() - t0, usage, u.get("cost"), 1)


def _openai_schema(s: Any) -> Any:
    """Gemini schema dialect (nullable, propertyOrdering) -> JSON Schema."""
    if isinstance(s, dict):
        out = {k: _openai_schema(v) for k, v in s.items() if k not in ("propertyOrdering", "nullable")}
        if s.get("nullable"):
            t = out.get("type")
            out["type"] = [t, "null"] if isinstance(t, str) else t
            if "enum" in out:
                out["enum"] = [*out["enum"], None]
        if out.get("type") == "object":
            out.setdefault("additionalProperties", False)
            out["required"] = list(out.get("properties", {}))
        return out
    if isinstance(s, list):
        return [_openai_schema(x) for x in s]
    return s


# ------------------------------------------------------------------ replay / record
class ReplayClient:
    """Answers from <dir>/<key>.json. `key` = body fingerprint or an explicit cache_key."""

    provider = "replay"

    def __init__(self, directory: Path, name: str = "replay", fallback_key: str | None = None):
        self.dir = Path(directory)
        self.name = name
        self.fallback_key = fallback_key

    def path_for(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def generate(self, body: dict, *, cache_key: str | None = None) -> LLMResult:
        keys = [k for k in (cache_key, body_fingerprint(body), self.fallback_key) if k]
        for k in keys:
            p = self.path_for(k)
            if p.exists():
                rec = json.loads(p.read_text(encoding="utf-8"))
                raw = rec.get("raw", rec)
                usage = usage_from_raw(raw)
                model = rec.get("model", "replay")
                # recorded n8n answers have no per-call latency: None keeps them out of latency metrics
                lat = rec.get("latency_s")
                return LLMResult(raw, model, "replay", float(lat) if lat is not None else float("nan"), usage,
                                 cost_usd(model, usage), replayed=True)
        raise LLMError(f"replay: no recorded answer for {keys[0] if keys else '?'} in {self.dir}", None, False)


class RecordingClient:
    """Wraps a live client and stores every answer for later replay (evals cache)."""

    def __init__(self, inner: VisionLLM, directory: Path):
        self.inner = inner
        self.name = inner.name
        self.provider = getattr(inner, "provider", "?")
        self.dir = Path(directory)

    def generate(self, body: dict, *, cache_key: str | None = None) -> LLMResult:
        key = cache_key or body_fingerprint(body, self.name)
        p = self.dir / f"{key}.json"
        if p.exists():
            return ReplayClient(self.dir).generate(body, cache_key=key)
        res = self.inner.generate(body, cache_key=cache_key)
        self.dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"model": res.model, "latency_s": res.latency_s, "raw": res.raw}, ensure_ascii=False),
                     encoding="utf-8")
        return res


class FallbackChain:
    def __init__(self, clients: list[VisionLLM]):
        if not clients:
            raise ValueError("empty LLM chain")
        self.clients = clients
        self.name = clients[0].name

    def generate(self, body: dict, *, cache_key: str | None = None) -> LLMResult:
        failed: list[str] = []
        last: Exception | None = None
        for c in self.clients:
            try:
                res = c.generate(body, cache_key=cache_key)
                res.fallback_from = failed
                return res
            except LLMError as e:
                failed.append(f"{c.name}: {e}")
                last = e
        raise LLMError("all models failed: " + " | ".join(failed)) from last


@traceable(run_type="llm", name="gemini.generateContent")
def call_llm(client: VisionLLM, body: dict, *, pass_name: str, cache_key: str | None = None) -> dict:
    """Traced call. Returns a plain dict (LangSmith reads usage_metadata from outputs)."""
    res = client.generate(body, cache_key=cache_key)
    return {
        "raw": res.raw,
        "model": res.model,
        "provider": res.provider,
        "latency_s": None if res.latency_s != res.latency_s else round(res.latency_s, 3),  # NaN -> unknown
        "cost_usd": res.cost_usd,
        "replayed": res.replayed,
        "fallback_from": res.fallback_from,
        "pass": pass_name,
        "usage_metadata": {"input_tokens": res.usage.get("input_tokens", 0), "output_tokens": res.usage.get("output_tokens", 0),
                           "total_tokens": (res.usage.get("input_tokens", 0) + res.usage.get("output_tokens", 0))},
    }


def build_chain(models: list[str], settings, *, pass_name: str) -> VisionLLM:
    """Client for a pass according to settings.llm_mode (live | replay | record)."""
    replay_dir = Path(settings.replay_dir) / pass_name
    if settings.llm_mode == "replay":
        return ReplayClient(replay_dir, name=f"replay:{pass_name}")
    clients: list[VisionLLM] = []
    if settings.gemini_api_key:
        clients += [GeminiClient(m, settings.gemini_api_key, settings.gemini_base_url, settings.llm_timeout_s,
                                 settings.llm_max_retries) for m in models]
    if settings.openrouter_api_key and settings.openrouter_model:
        clients.append(OpenRouterClient(settings.openrouter_model, settings.openrouter_api_key))
    if not clients:
        raise LLMError("no LLM configured: set GEMINI_API_KEY (or LLM_MODE=replay for recorded answers)")
    chain: VisionLLM = FallbackChain(clients)
    if settings.llm_mode == "record":
        chain = RecordingClient(chain, replay_dir)
    return chain


def inline_file(path: Path, mime: str) -> dict:
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(Path(path).read_bytes()).decode("ascii")}}
