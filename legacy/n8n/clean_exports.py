#!/usr/bin/env python3
"""Sanitise n8n workflow exports before they enter git (historical artefact only, never imported).

Removes: pinData (pinned execution data), instance/version/workflow ids, credential ids and names,
webhook ids, Google Sheet / Drive ids and URLs, literal Telegram chat ids, anything that looks like a
bot token or an API key. Keeps: nodes, code, prompts, connections — the logic the new system ports.

    python legacy/n8n/clean_exports.py --source "C:/.../Artyom" MainWF_v9.2_sheets_cold.json WF2_v4.3_noreven.json ...
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
PATTERNS = [
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"), "<BOT_TOKEN>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "<GOOGLE_API_KEY>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "<API_KEY>"),
    (re.compile(r"docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+"), "docs.google.com/spreadsheets/d/<SHEET_ID>"),
    (re.compile(r"drive\.google\.com/[^\s\"']+"), "drive.google.com/<REDACTED>"),
    (re.compile(r"generativelanguage\.googleapis\.com/v1beta/files/[a-z0-9]+"), "generativelanguage.googleapis.com/v1beta/files/<FILE>"),
    (re.compile(r'^=\d{6,}$'), "=<CHAT_ID>"),
    (re.compile(r"\b1[A-Za-z0-9_-]{32,43}\b"), "<GOOGLE_ID>"),  # Sheets / Drive ids
]
DROP_TOP = {"pinData", "id", "versionId", "meta", "shared", "triggerCount", "staticData"}


def scrub(v, stats):
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k == "webhookId":
                out[k] = "<WEBHOOK_ID>"
                stats["webhook"] += 1
            elif k == "credentials" and isinstance(x, dict):
                out[k] = {ck: {"id": "<CRED_ID>", "name": f"<{ck}>"} for ck in x}
                stats["credentials"] += len(x)
            elif k in ("cachedResultUrl", "cachedResultName") and isinstance(x, str):
                out[k] = "<REDACTED>"
            else:
                out[k] = scrub(x, stats)
        return out
    if isinstance(v, list):
        return [scrub(x, stats) for x in v]
    if isinstance(v, str):
        s = v
        for rx, rep in PATTERNS:
            s, n = rx.subn(rep, s)
            stats["strings"] += n
        return s
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    for name in a.files:
        wf = json.loads((a.source / name).read_text(encoding="utf-8"))
        stats = {"webhook": 0, "credentials": 0, "strings": 0}
        dropped = [k for k in DROP_TOP if k in wf]
        clean = scrub({k: v for k, v in wf.items() if k not in DROP_TOP}, stats)
        (OUT / name).write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name}: dropped {dropped}; redacted {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
