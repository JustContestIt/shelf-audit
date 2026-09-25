"""Versioned prompts. One file per version; the body is sent byte-for-byte.

File format: YAML-ish front matter (id, version, pass, source, status) + body.
The version string goes to LangSmith tags and to every report row, so any number in
EVALS.md can be traced back to the exact text that produced it.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    pass_: str
    text: str
    meta: dict


@lru_cache
def load_prompt(prompt_id: str) -> Prompt:
    path = PROMPTS_DIR / f"{prompt_id}.md"
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"{path}: no front matter")
    head, body = raw[4:].split("\n---\n", 1)
    meta = {}
    for line in head.splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    if body.endswith("\n"):
        body = body[:-1]
    return Prompt(id=meta.get("id", prompt_id), version=meta["version"], pass_=meta.get("pass", ""), text=body, meta=meta)


def available() -> list[str]:
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))
