#!/usr/bin/env python3
"""Copy the prompt history (archive/ in the working folder) into legacy/prompts/ with redaction.

The plan says: archive/ is not migrated, except the prompt history. These files are the
BUILD notes where every prompt version was written down together with the failure it fixed.
Redacted on copy: Telegram chat ids / other long numeric ids, store names from test frames,
anything that looks like a bot token or a Google Sheet id. Run gitleaks after re-importing.

    python legacy/prompts/import_history.py --artyom "C:/.../Artyom"
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
FILES = [  # (source relative to the working folder, name in legacy/prompts/)
    ("archive/early_setup_and_prompts/gemini_vision_setup_n8n.md", "v0_setup_n8n.md"),
    ("archive/early_setup_and_prompts/vision_prompt_FINAL.md", "v1_FINAL.md"),
    ("archive/catalog_and_subtypes/vision_prompt_SUBTYPES.md", "v2_SUBTYPES.md"),
    ("archive/early_setup_and_prompts/vision_prompt_v3_RESTRUCTURED.md", "v3_RESTRUCTURED.md"),
    ("archive/early_setup_and_prompts/vision_prompt_v4_ENUMERATION.md", "v4_ENUMERATION.md"),
    ("archive/early_setup_and_prompts/vision_prompt_v5_V1_PLUS_SUBTYPES.md", "v5_V1_PLUS_SUBTYPES.md"),
    ("wf2_twostage_BUILD.md", "v5b_twostage_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/vision_architecture_DETECTION.md", "v6_architecture_DETECTION.md"),
    ("archive/vision_pipeline_v6_v9/wf2_v6_detection_BUILD.md", "v6_detection_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/wf2_v7_format_BUILD.md", "v7_format_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/wf2_v71_twins_BUILD.md", "v7.1_twins_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/wf2_v72_subtype_BUILD.md", "v7.2_subtype_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/wf2_v73_subtype_BUILD.md", "v7.3_subtype_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/wf2_v74_subtype_BUILD.md", "v7.4_subtype_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/wf2_v8_hybrid_BUILD.md", "v8_hybrid_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/wf2_v8_pro_pass_BUILD.md", "v8_pro_pass_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/pass2_v9_groups_BUILD.md", "v9_groups_pass2_BUILD.md"),
    ("archive/vision_pipeline_v6_v9/format_width_BUILD.md", "v7.5_format_geo_BUILD.md"),
    ("REVEN_OFF_BUILD.md", "v7.4_noreven_BUILD.md"),
    ("PROMPT_bgcolor_BUILD.md", "v7.5_bgcolor_BUILD.md"),
]
# Store names to redact live outside git: data/redact_words.txt (one per line) or --redact "a,b".
REDACT_FILE = OUT.parents[1] / "data" / "redact_words.txt"
RULES = [
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{10,}"), "<bot_token>"),       # Telegram token (full or partial)
    (re.compile(r"\b1[A-Za-z0-9_-]{40,}\b"), "<sheet_id>"),               # Google file / sheet id
    (re.compile(r"(?<![\w.])-?\d{7,}(?![\w.])"), "<id>"),                   # chat ids, user ids
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),
    (re.compile(r"\+?7[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"), "<phone>"),
]


def redact(text: str, words: list[str]) -> tuple[str, int]:
    n = 0
    for s in sorted(words, key=len, reverse=True):
        n += text.count(s)
        text = text.replace(s, "<магазин>")
    for rx, rep in RULES:
        text, k = rx.subn(rep, text)
        n += k
    return text, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artyom", required=True, help="the working folder (with archive/)")
    ap.add_argument("--redact", default="", help="extra comma-separated words to replace with <магазин>")
    a = ap.parse_args()
    root = Path(a.artyom)
    words = [w.strip() for w in a.redact.split(",") if w.strip()]
    if REDACT_FILE.exists():
        words += [w.strip() for w in REDACT_FILE.read_text(encoding="utf-8").splitlines() if w.strip()]
    if not words:
        print("!! no store names to redact: put them into data/redact_words.txt (not in git)")
    for src, dst in FILES:
        p = root / src
        if not p.exists():
            print(f"  missing: {src}")
            continue
        text, n = redact(p.read_text(encoding="utf-8"), words)
        header = f"<!-- imported from the working folder: {src}; redactions: {n} -->\n"
        (OUT / dst).write_text(header + text, encoding="utf-8")
        print(f"{dst:34s} {len(text):6d} chars, {n} redactions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
