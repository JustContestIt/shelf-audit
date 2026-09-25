#!/usr/bin/env python3
"""Turn the recorded n8n runs into replay-cache entries for the new pipeline.

For every run in backend/tests/fixtures/n8n_runs/ the recorded pass-1 boxes and the pass-2
names become model answers stored under the cache keys the LangGraph pipeline computes for the
same frame and config (salt = run name). Then `python -m evals.run --config configs/n8n_*_replay.yaml`
pushes 33 historical answers through the new graph and scores them with the new scorers: the
"before migration" numbers of EVALS.md come out of the same framework as the new ones.

    python evals/tools/n8n_to_cache.py --config evals/configs/n8n_v74_replay.yaml
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO))

from app.config import Settings  # noqa: E402
from app.graph.deps import build_deps  # noqa: E402
from app.storage.repo import MemoryRepo  # noqa: E402
from app.vision.postprocess import UNKNOWN, plan_groups, postprocess_detect  # noqa: E402
from evals.run import load_golden, photo_for  # noqa: E402

RUNS = REPO / "backend" / "tests" / "fixtures" / "n8n_runs"


def raw(data: dict, usage: dict | None) -> dict:
    u = usage or {}
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(data, ensure_ascii=False)}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": u.get("prompt_tokens"), "cachedContentTokenCount": u.get("cached_tokens"),
                              "candidatesTokenCount": u.get("output_tokens")}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--salt", default=None, help="store under this salt instead of the run name ('' = the API default)")
    a = ap.parse_args()
    cfg = yaml.safe_load(a.config.read_text(encoding="utf-8"))
    s = Settings(**(cfg.get("settings") or {}), llm_mode="replay", database_url=None, replay_dir=REPO / "evals" / "cache",
                 config_id=cfg["name"])
    deps = build_deps(s, repo=MemoryRepo(), retriever=None)
    frames = {f["frame_id"]: f for f in load_golden("all")}
    written = 0
    for frame_id, salts in (cfg.get("replay_salts") or {}).items():
        photo = photo_for(frames[frame_id], "orig", s.data_dir)
        sha = hashlib.sha256(photo.read_bytes()).hexdigest()
        refs = [r.key for r in deps.active_refs()]
        for salt in salts:
            run = json.loads((RUNS / f"{salt}.json").read_text(encoding="utf-8"))
            s.cache_salt = salt if a.salt is None else a.salt
            d = run["pass1"]["_detect"]
            data = {"boxes": list(d.get("boxes_raw") or []) + list(d.get("slivers_raw") or []),
                    "overall_confidence": run["pass1"].get("overall_confidence", 0.9), "notes": run["pass1"].get("notes", "")}
            det_raw = raw(data, run["pass1"].get("_usage"))
            key = deps.cache_key("detect", sha, refs=refs)
            (s.replay_dir / "detect").mkdir(parents=True, exist_ok=True)
            (s.replay_dir / "detect" / f"{key}.json").write_text(
                json.dumps({"model": "gemini-3.5-flash", "latency_s": None, "raw": det_raw, "source": f"n8n:{salt}"},
                           ensure_ascii=False), encoding="utf-8")
            written += 1
            p2 = (run.get("pass2") or {}).get("_pass2") or {}
            if not p2.get("detail") or s.pass2_mode in ("off", "check"):
                continue
            parsed = postprocess_detect(data)
            plan = plan_groups(parsed["_detect"]["boxes_raw"])
            shelves = []
            for sh in p2["detail"]:
                if sh.get("shelf") is None:
                    continue
                gs = []
                for g in sh.get("groups") or []:
                    if g.get("applied"):
                        gs.append({"group_index": g["gi"], "subtype": g["name"]})
                    elif g.get("needs_review"):
                        gs.append({"group_index": g["gi"], "subtype": UNKNOWN})
                    elif str(g.get("reason", "")).startswith("подпись чужого бренда: "):
                        gs.append({"group_index": g["gi"], "subtype": g["reason"].split(": ", 1)[1]})
                shelves.append({"shelf_index": sh["shelf"], "groups": gs})
            vkey = deps.cache_key("verify", sha, refs=refs,
                                  plan=[[p["shelf_index"], [[g["group_index"], g["size"], g["brand"]] for g in p["groups"]]] for p in plan],
                                  attempt=0)
            (s.replay_dir / "verify").mkdir(parents=True, exist_ok=True)
            (s.replay_dir / "verify" / f"{vkey}.json").write_text(
                json.dumps({"model": "gemini-3.5-flash", "latency_s": None, "raw": raw({"shelves": shelves}, (p2.get("usage") or {})),
                            "source": f"n8n:{salt}"}, ensure_ascii=False), encoding="utf-8")
            written += 1
    print(f"{written} cache entries -> {s.replay_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
