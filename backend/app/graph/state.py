"""Graph state. One photo = one run of the graph, thread_id == report_id.

Big blobs never live in the state (it is checkpointed to Postgres on every step): the photo
is a file on disk referenced by path + sha256; the model answers are kept only in parsed form.
"""
from __future__ import annotations

import operator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Status = Literal["new", "queued", "rejected", "detecting", "verifying", "awaiting_review", "approved", "edited",
                 "retake", "failed"]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Photo(BaseModel):
    path: str
    sha256: str = ""
    phash: str = ""
    mime: str | None = None
    width: int = 0
    height: int = 0
    bytes: int = 0
    blur: float = 0.0
    exif: dict = Field(default_factory=dict)
    source: str = "api"          # api | bot | eval | mcp
    frame_id: str | None = None  # golden-set id when known (evals)


class Store(BaseModel):
    store_code: str = ""
    store_name: str = ""
    route_code: str = ""
    agent_id: str = ""
    chat_id: str | None = None


class LLMCall(BaseModel):
    pass_: str = Field(alias="pass")
    model: str
    provider: str
    latency_s: float | None = None
    cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    replayed: bool = False
    fallback_from: list[str] = Field(default_factory=list)
    at: str = Field(default_factory=now_iso)

    model_config = {"populate_by_name": True}


class ReportRow(BaseModel):
    shelf_index: int
    position: str                 # слева / центр / справа
    brand: str
    subtype: str | None
    package_format: str | None
    front_facing_count: int
    needs_review: bool = False
    review_reason: str | None = None
    group_keys: list[str] = Field(default_factory=list)  # "shelf.gi" of the pass-2 groups inside the row


class Report(BaseModel):
    rows: list[ReportRow] = Field(default_factory=list)
    total_units: int = 0
    shelves: int = 0
    unknown_units: int = 0        # subtype null -> block «не опознано» (BACKLOG №28)
    needs_review_units: int = 0   # BACKLOG №27
    foreign_units: int = 0        # diagnostics only, never counted
    suspected_foreign_units: int = 0  # our label, but SigLIP says "not like our refs" (excluded or flagged)
    overall_confidence: float | None = None
    low_confidence: bool = False
    flags: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    latency_s: float | None = 0.0


class Review(BaseModel):
    action: Literal["approve", "edit", "retake"]
    edits: list[dict] = Field(default_factory=list)
    reviewer: str | None = None
    comment: str | None = None
    photo_path: str | None = None  # for retake
    at: str = Field(default_factory=now_iso)


class Progress(BaseModel):
    node: str
    at: str = Field(default_factory=now_iso)
    info: str = ""


class AuditState(BaseModel):
    report_id: str
    photo: Photo
    store: Store = Field(default_factory=Store)
    status: Status = "new"
    reject_reason: str | None = None
    config_id: str = "default"
    prompt_version: str = ""
    verify_prompt_version: str = ""

    guard: dict[str, Any] = Field(default_factory=dict)
    detect: dict[str, Any] = Field(default_factory=dict)       # n8n-shaped «Парсинг» output
    merged: dict[str, Any] = Field(default_factory=dict)       # n8n-shaped «Слияние» output (or = detect)
    uncertain: list[list[int]] = Field(default_factory=list)   # [[shelf, group_index], ...] still to verify
    verified_boxes: list[str] = Field(default_factory=list)    # json(box_2d) of boxes already seen by pass 2
    needs_review_groups: list[list[int]] = Field(default_factory=list)
    suspected_boxes: list[str] = Field(default_factory=list)      # json(box_2d) of units that look like competitors
    retrieval: dict[str, Any] = Field(default_factory=dict)    # "shelf.gi" -> candidates
    verify_attempts: int = 0
    report: Report | None = None
    review: Review | None = None
    retakes: int = 0

    progress: Annotated[list[Progress], operator.add] = Field(default_factory=list)
    llm_calls: Annotated[list[LLMCall], operator.add] = Field(default_factory=list)
    errors: Annotated[list[str], operator.add] = Field(default_factory=list)
