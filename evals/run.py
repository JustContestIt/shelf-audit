"""Eval runner: golden frames -> the real LangGraph pipeline -> scorers -> results/<name>_<ts>.json.

    python -m evals.run --config evals/configs/baseline.yaml               # live Gemini, responses cached
    python -m evals.run --config evals/configs/n8n_v74_replay.yaml         # recorded n8n answers, no key needed
    python -m evals.run --config evals/configs/baseline.yaml --mode replay # re-score cached answers for free

The pipeline runs exactly as in production (AuditService, same graph, same postprocess) and stops
at human_review; the scorer reads the final boxes. Every model answer is cached by
hash(photo + prompt + refs + config [+ repeat salt]) in evals/cache/, so recomputing metrics after
a scorer change costs nothing. With LANGSMITH_API_KEY the run is also uploaded as an experiment.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.config import Settings  # noqa: E402
from app.graph.deps import build_deps  # noqa: E402
from app.graph.state import Store  # noqa: E402
from app.service import AuditService  # noqa: E402
from app.storage.repo import MemoryRepo  # noqa: E402
from app.vision.crops import load_image, telegram_sim, to_jpeg_bytes  # noqa: E402
from evals.scorers.metrics import aggregate, score_frame, slices  # noqa: E402

GOLDEN = REPO / "evals" / "golden"
RESULTS = REPO / "evals" / "results"
TG_DIR = REPO / "evals" / "frames_tg"


def load_golden(selector) -> list[dict]:
    idx = json.loads((GOLDEN / "INDEX.json").read_text(encoding="utf-8"))
    frames = [json.loads((GOLDEN / f"{i['frame_id']}.json").read_text(encoding="utf-8")) for i in idx]
    frames = [f for f in frames if f.get("file")]
    if selector in (None, "all"):
        return frames
    if isinstance(selector, str):
        selector = [selector]
    return [f for f in frames if f["frame_id"] in selector or f["tier"] in selector]


def photo_for(frame: dict, variant: str, data_dir: Path) -> Path:
    src = data_dir / frame["file"]
    if variant == "orig":
        return src
    if variant == "tg1280":
        TG_DIR.mkdir(parents=True, exist_ok=True)
        dst = TG_DIR / f"{frame['frame_id']}_tg1280.jpg"
        if not dst.exists():
            dst.write_bytes(to_jpeg_bytes(telegram_sim(load_image(src), 1280, 80), 80))
        return dst
    raise ValueError(variant)


def run_one(svc: AuditService, repo: MemoryRepo, frame: dict, variant: str, salt: str, data_dir: Path) -> dict:
    svc.deps.settings.cache_salt = salt
    path = photo_for(frame, variant, data_dir)
    t0 = time.time()
    rid = svc.submit_path(path, Store(store_code="EVAL", store_name=frame["frame_id"]), source="eval",
                          frame_id=frame["frame_id"], wait=True, copy=False)
    rec = repo.get_report(rid) or {}
    body = rec.get("body") or {}
    out = {"frame_id": frame["frame_id"], "variant": variant, "repeat": salt, "tier": frame["tier"], "report_id": rid,
           "status": rec.get("status"), "wall_s": round(time.time() - t0, 1), "cost_usd": rec.get("cost_usd"),
           "latency_s": rec.get("latency_s"), "flags": rec.get("flags") or [], "models": rec.get("models"),
           "replayed": all(c.get("replayed") for c in body.get("llm_calls", [])) if body.get("llm_calls") else None}
    if rec.get("status") in ("awaiting_review", "approved", "edited"):
        out["score"] = score_frame(body.get("boxes") or [], frame)
        out["pass2"] = {k: (body.get("pass2") or {}).get(k) for k in ("version", "subtypes_changed", "needs_review")}
    else:
        out["error"] = rec.get("reject_reason") or ", ".join(out["flags"]) or rec.get("status")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--mode", choices=["live", "record", "replay"], help="override config mode")
    ap.add_argument("--frames", help="comma-separated frame ids (override)")
    ap.add_argument("--repeats", type=int)
    ap.add_argument("--langsmith", action="store_true", help="upload as a LangSmith experiment (needs LANGSMITH_API_KEY)")
    ap.add_argument("--skip", type=int, default=0, help="skip the first N runs of the plan (resume a long run)")
    ap.add_argument("--max-runs", type=int, help="run at most N runs")
    ap.add_argument("--tag", default="", help="suffix of the result name (e.g. part1)")
    a = ap.parse_args(argv)

    cfg = yaml.safe_load(a.config.read_text(encoding="utf-8"))
    mode = a.mode or cfg.get("mode", "record")
    overrides = dict(cfg.get("settings") or {})
    settings = Settings(**overrides, llm_mode=mode, database_url=None, replay_dir=REPO / "evals" / "cache",
                        config_id=cfg["name"], photos_dir=REPO / "evals" / ".uploads")
    repo = MemoryRepo()
    svc = AuditService(deps=build_deps(settings, repo=repo), settings=settings, workers=1)
    frames = load_golden(a.frames.split(",") if a.frames else cfg.get("frames", "gold"))
    variants = cfg.get("variants", ["orig"])
    repeats = a.repeats or cfg.get("repeats", 1)
    replay_salts: dict[str, list[str]] = cfg.get("replay_salts") or {}

    plan = []
    for f in frames:
        salts = replay_salts.get(f["frame_id"]) if replay_salts else [f"r{i}" for i in range(repeats)]
        if replay_salts and not salts:
            continue
        for v in (["orig"] if replay_salts else [x for x in variants if x in f.get("variants", ["orig"])]):
            for salt in salts:
                plan.append((f, v, salt))
    plan = plan[a.skip:][: a.max_runs] if a.max_runs else plan[a.skip:]
    print(f"[{cfg['name']}] mode={mode} runs={len(plan)} frames={[f['frame_id'] for f in frames]}")

    runs = []
    for i, (f, v, salt) in enumerate(plan, 1):
        r = run_one(svc, repo, f, v, salt, settings.data_dir)
        runs.append(r)
        sc = r.get("score")
        print(f"  {i:3d}/{len(plan)} {f['frame_id']:9s} {v:6s} {salt[:26]:26s} "
              + (f"count {sc['count_exact_shelves']}/{sc['shelves']} units {sc['units_pred']}/{sc['units_gt']} "
                 f"subtype err {sc['subtype_errors']}/{sc['subtype_scored']} contam {sc['contamination']} "
                 f"pack err {sc['pack_errors']}/{sc['pack_scored']}" if sc else f"FAILED: {r.get('error')}"))
    svc.shutdown()

    summary = aggregate(runs)
    res = {
        "name": cfg["name"], "description": cfg.get("description", ""),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"), "mode": mode,
        "config": {"settings": overrides, "frames": [f["frame_id"] for f in frames], "variants": variants,
                   "repeats": repeats if not replay_salts else "replay_salts", "prompt": svc.deps.detect_prompt.version,
                   "verify_prompt": svc.deps.verify_prompt.version, "models": settings.detect_models},
        "summary": summary, "slices": slices(runs),
        "per_frame": [{"frame_id": r["frame_id"], "variant": r["variant"], "repeat": r["repeat"], "tier": r["tier"],
                       "status": r["status"], "shelves": (r.get("score") or {}).get("shelves"),
                       "units_gt": (r.get("score") or {}).get("units_gt"), "units_pred": (r.get("score") or {}).get("units_pred"),
                       "count_exact_shelves": (r.get("score") or {}).get("count_exact_shelves"),
                       "subtype_errors": (r.get("score") or {}).get("subtype_errors"),
                       "contamination": (r.get("score") or {}).get("contamination"),
                       "pack_errors": (r.get("score") or {}).get("pack_errors"), "cost_usd": r.get("cost_usd"),
                       "latency_s": r.get("latency_s"), "pass2": r.get("pass2"),
                       "errors": ((r.get("score") or {}).get("errors") or [r.get("error")])[:40]} for r in runs],
        "notes": cfg.get("notes", ""),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{cfg['name']}{('_' + a.tag) if a.tag else ''}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nsummary:")
    for k, v in summary.items():
        print(f"  {k:30s} {v}")
    print(f"-> {out}")
    if a.langsmith:
        from evals.langsmith_upload import upload

        upload(res, runs)
    return 0 if summary["n_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
