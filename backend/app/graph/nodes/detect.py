"""detect (Gemini pass 1) and postprocess (deterministic count from boxes)."""
from __future__ import annotations

from pathlib import Path

from app.catalog import subtype_enum
from app.graph.deps import Deps
from app.graph.state import AuditState, LLMCall, Progress
from app.guardrails.output_schema import validate_detect
from app.vision.crops import b64
from app.vision.llm import LLMError, call_llm
from app.vision.postprocess import extract_text_json, postprocess_detect, usage_of
from app.vision.requests import detect_request, photo_part


def llm_call_record(res: dict) -> LLMCall:
    u = res["usage_metadata"]
    raw_u = res["raw"].get("usageMetadata") or {}
    return LLMCall(**{"pass": res["pass"]}, model=res["model"], provider=res["provider"], latency_s=res["latency_s"],
                   cost_usd=res["cost_usd"], input_tokens=u["input_tokens"], output_tokens=u["output_tokens"],
                   cached_tokens=raw_u.get("cachedContentTokenCount") or 0, replayed=res["replayed"],
                   fallback_from=res["fallback_from"])


def make_detect(deps: Deps):
    def detect(state: AuditState) -> dict:
        refs = deps.active_refs()
        prompt = deps.detect_prompt
        photo = photo_part(b64(Path(state.photo.path).read_bytes()), state.photo.mime, deps.settings.media_resolution)
        body = detect_request(refs, photo, prompt.text, deps.gen(), deps.ref_parts)
        key = deps.cache_key("detect", state.photo.sha256, refs=[r.key for r in refs])
        try:
            res = call_llm(deps.detect_llm, body, pass_name="detect", cache_key=key)
        except LLMError as e:
            return {"status": "failed", "errors": [f"detect: {e}"[:500]],
                    "progress": [Progress(node="detect", info="модель не ответила")]}
        return {"detect": {"_raw": res["raw"]}, "prompt_version": prompt.version, "llm_calls": [llm_call_record(res)],
                "progress": [Progress(node="detect", info=f"{res['model']}, " + (f"{res['latency_s']:.0f} с" if res["latency_s"] is not None else "время не записано")
                                      + (" (replay)" if res["replayed"] else ""))]}

    return detect


def make_postprocess(deps: Deps):
    def postprocess(state: AuditState) -> dict:
        raw = state.detect.get("_raw") or {}
        try:
            data, finish = extract_text_json(raw)
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "errors": [f"postprocess: {e}"[:500]],
                    "progress": [Progress(node="postprocess", info="ответ модели не разобрался")]}
        issues = validate_detect(data, subtype_enum(deps.active_refs()))
        u = usage_of(raw)
        parsed = postprocess_detect(data, finish_reason=finish, geo=deps.geo,
                                    usage={k: u[k] for k in ("prompt_tokens", "cached_tokens", "output_tokens")})
        if finish and finish not in ("STOP", "stop"):
            issues.append(f"вывод модели оборван: finishReason={finish}")
        parsed["_issues"] = issues
        d = parsed["_detect"]
        info = (f"боксов {d['boxes_total']}, наших {sum(i['front_facing_count'] for i in parsed['items'])}, "
                f"чужих {d['foreign_units']}, щепок {d['slivers_dropped']}")
        return {"detect": parsed, "merged": parsed, "status": "verifying",
                "errors": [f"output_guard: {i}" for i in issues],
                "progress": [Progress(node="postprocess", info=info)]}

    return postprocess


def route_after_detect(state: AuditState) -> str:
    return "build_report" if state.status == "failed" else "postprocess"
