"""Output guardrails: the model's JSON is validated before any number reaches a report.

* schema: Pydantic models mirror the response_schema sent to Gemini (enum of labels/subtypes/
  formats, 4-int boxes). Structured output makes violations rare; we still check, because a
  fallback model (OpenRouter) may not enforce the schema the same way.
* hard gate "чужие = 0": units labelled ЧУЖОЙ never enter counts (by construction in
  postprocess); build_report asserts it again on the final rows.
* plausibility: truncated output (finishReason MAX_TOKENS), absurd unit counts, a subtype of
  another brand -> the report is marked needs_review instead of silently published.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.catalog import BRANDS, FOREIGN, FORMATS, UNKNOWN


class DetectBox(BaseModel):
    box_2d: list[float] = Field(min_length=4, max_length=4)
    label: str
    subtype: str | None = None
    format: str | None = None
    shelf_index: int | float | None = None
    confidence: float | None = None

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        if v not in (*BRANDS, FOREIGN):
            raise ValueError(f"unknown label {v!r}")
        return v

    @field_validator("format")
    @classmethod
    def _fmt(cls, v):
        if v is not None and v not in FORMATS:
            raise ValueError(f"unknown format {v!r}")
        return v


class DetectOutput(BaseModel):
    boxes: list[DetectBox]
    store_code_on_card: str | None = None
    overall_confidence: float | None = None
    notes: str | None = ""


class VerifyGroup(BaseModel):
    group_index: int
    subtype: str


class VerifyShelf(BaseModel):
    shelf_index: int
    groups: list[VerifyGroup]


class VerifyOutput(BaseModel):
    shelves: list[VerifyShelf]


MAX_UNITS_PER_SHELF = 60
MAX_UNITS_TOTAL = 300


def validate_detect(data: dict, subtypes: list[str]) -> list[str]:
    """Problems found in a pass-1 answer (empty = fine). Does not raise: n8n parsing is lenient
    (bad boxes are dropped and counted), the problems go to the report as flags."""
    issues = []
    try:
        out = DetectOutput.model_validate(data)
    except Exception as e:  # noqa: BLE001
        return [f"schema: {str(e).splitlines()[0][:200]}"]
    allowed = set(subtypes)
    bad_sub = [b.subtype for b in out.boxes if b.subtype and b.subtype not in allowed]
    if bad_sub:
        issues.append(f"subtype вне каталога: {sorted(set(bad_sub))[:5]}")
    mixed = [b for b in out.boxes if b.subtype and b.label in BRANDS and b.label != "Tamga" and not b.subtype.startswith(b.label)]
    if mixed:
        issues.append(f"подвид чужого бренда у {len(mixed)} боксов")
    per_shelf: dict = {}
    for b in out.boxes:
        per_shelf[b.shelf_index] = per_shelf.get(b.shelf_index, 0) + 1
    if len(out.boxes) > MAX_UNITS_TOTAL or any(v > MAX_UNITS_PER_SHELF for v in per_shelf.values()):
        issues.append(f"неправдоподобно много боксов: {len(out.boxes)}")
    return issues


def validate_verify(data: dict, subtypes: list[str]) -> list[str]:
    try:
        out = VerifyOutput.model_validate(data)
    except Exception as e:  # noqa: BLE001
        return [f"schema: {str(e).splitlines()[0][:200]}"]
    allowed = set(subtypes) | {UNKNOWN}
    bad = [g.subtype for s in out.shelves for g in s.groups if g.subtype not in allowed]
    return [f"subtype вне enum: {sorted(set(bad))[:5]}"] if bad else []
