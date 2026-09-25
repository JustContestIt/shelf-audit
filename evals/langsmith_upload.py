"""Upload an eval run to LangSmith as a dataset + experiment (optional; needs LANGSMITH_API_KEY).

Dataset "shelf-audit-golden": one example per (frame, variant) with the GT shelves as outputs.
Experiment "<config name>": one run per (frame, variant, repeat) with the predicted counts and the
metrics as feedback (count_exact_rate, subtype_acc, contamination, pack_acc, cost_usd).
Traces of the graph runs themselves are already in the LangSmith project when LANGSMITH_TRACING=true.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "golden"
DATASET = "shelf-audit-golden"


def upload(result: dict, runs: list[dict]) -> None:
    if not os.environ.get("LANGSMITH_API_KEY"):
        print("LANGSMITH_API_KEY is not set — skipping upload")
        return
    from langsmith import Client

    client = Client()
    try:
        ds = client.read_dataset(dataset_name=DATASET)
    except Exception:  # noqa: BLE001
        ds = client.create_dataset(DATASET, description="Shelf-audit golden set: frames x shelves with positional GT")
    existing = {(e.inputs.get("frame_id"), e.inputs.get("variant")): e for e in client.list_examples(dataset_id=ds.id)}
    for r in runs:
        key = (r["frame_id"], r["variant"])
        if key not in existing:
            gt = json.loads((GOLDEN / f"{r['frame_id']}.json").read_text(encoding="utf-8"))
            existing[key] = client.create_example(
                inputs={"frame_id": r["frame_id"], "variant": r["variant"], "tier": gt["tier"]},
                outputs={"shelves": [{"shelf_index": s["shelf_index"], "units_gt": s["units_gt"]} for s in gt["shelves"]]},
                dataset_id=ds.id)
    project = f"eval:{result['name']}:{result['created_at']}"
    for r in runs:
        ex = existing[(r["frame_id"], r["variant"])]
        sc = r.get("score") or {}
        run_id = client.create_run(
            name=f"{r['frame_id']}/{r['variant']}/{r['repeat']}", run_type="chain", project_name=project,
            inputs={"frame_id": r["frame_id"], "variant": r["variant"]}, reference_example_id=ex.id,
            outputs={"units_pred": sc.get("units_pred"), "errors": sc.get("errors", [])[:20], "status": r.get("status")},
            extra={"metadata": {"config": result["name"], **(result.get("config") or {}).get("settings", {})}},
        )
        if not sc:
            continue
        feedback = {
            "count_exact_rate": sc["count_exact_shelves"] / sc["shelves"] if sc["shelves"] else None,
            "subtype_acc": 1 - sc["subtype_errors"] / sc["subtype_scored"] if sc["subtype_scored"] else None,
            "contamination": sc["contamination"],
            "pack_acc": 1 - sc["pack_errors"] / sc["pack_scored"] if sc["pack_scored"] else None,
            "cost_usd": r.get("cost_usd"),
        }
        for k, v in feedback.items():
            if v is not None and run_id is not None:
                client.create_feedback(run_id, key=k, score=v)
    print(f"LangSmith: dataset {DATASET}, experiment project {project}")
