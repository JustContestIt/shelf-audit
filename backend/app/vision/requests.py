"""Gemini request bodies for pass 1 (detect) and pass 2 (verify).

Port of the n8n nodes «Сборка запроса Gemini» (v7.x) and «Сборка запроса Pro» (v9).
The body is the same JSON that n8n sent (REST generateContent), so a live run here and a
run in n8n are comparable; tests/test_prompts.py checks byte-for-byte equality with the JS.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.catalog import BRANDS, FOREIGN, FORMATS, UNKNOWN, Ref, subtype_enum
from app.vision.postprocess import plan_groups, plan_text

RefPartFn = Callable[[Ref], dict]
MIME_OK = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


@dataclass
class GenConfig:
    temperature: float | None = 0.0
    thinking_level: str | None = None
    max_output_tokens: int | None = None
    top_p: float | None = None
    media_resolution: str | None = "MEDIA_RESOLUTION_ULTRA_HIGH"  # per-part, target photo only
    extra: dict = field(default_factory=dict)

    def generation_config(self, schema: dict) -> dict:
        g: dict = {}
        if self.temperature is not None:
            g["temperature"] = self.temperature
        g["response_mime_type"] = "application/json"
        g["response_schema"] = schema
        if self.top_p is not None:
            g["topP"] = self.top_p
        if self.max_output_tokens is not None:
            g["maxOutputTokens"] = self.max_output_tokens
        if self.thinking_level:
            g["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        g.update(self.extra)
        return g


# ------------------------------------------------------------------ variants (README_ALL grammar)
def variant_of(r: Ref) -> str | None:
    if r.variant:
        return str(r.variant)
    i = r.key.find("__")
    return None if i == -1 else r.key[i + 2:]


def variant_note(v: str | None) -> str | None:
    if not v:
        return None
    parts = []
    if re.search(r"(^|_)kz($|_)", v):
        parts.append("этикетка на казахском")
    if re.search(r"(^|_)ru($|_)", v):
        parts.append("этикетка на русском")
    if "rot" in v:
        parts.append("повёрнутый ракурс")
    if v == "field":
        parts.append("полевое фото с полки")
    if v.startswith("can900"):
        parts.append("банка 0,9 л")
    elif v.startswith("can"):
        parts.append("банка крупным планом")
    if v.startswith("sleever"):
        parts.append("ПЭТ-бутылка 1 л с цветным рукавом")
    if v.startswith("pet1000"):
        parts.append("ПЭТ-бутылка 1 л")
    else:
        m = re.match(r"^pet(\d+)", v)
        if m:
            vol = {"025": "0,25", "05": "0,5", "1": "1", "15": "1,5", "2": "2", "24": "2,4"}.get(m.group(1), m.group(1))
            parts.append("ПЭТ-бутылка " + vol + " л")
    return ", ".join(parts) if parts else "дополнительный ракурс (" + v + ")"


def reference_parts(refs: list[Ref], ref_part: RefPartFn, js_quotes: bool = True) -> list[dict]:
    """СПРАВОЧНИК block: header, then per ref a text label + image part."""
    has_variants = any(variant_of(r) for r in refs)
    parts = [{"text": "СПРАВОЧНИК ПОДВИДОВ КОМПАНИИ. Далее эталонные изображения; перед каждым — его канон-имя и бренд"
              + ("; у подвида может быть несколько эталонов (другой язык этикетки, другой ракурс или другая тара) — это один и тот же подвид"
                 if has_variants else "") + ":"}]
    seen: set[str] = set()
    for r in refs:
        note = variant_note(variant_of(r))
        if r.canon_name not in seen:
            seen.add(r.canon_name)
            parts.append({"text": f"Эталон: «{r.canon_name}» — бренд {r.brand}." + (f" ({note})" if note else "")})
        else:
            parts.append({"text": f"Тот же подвид «{r.canon_name}», {note or 'дополнительный эталон'}."})
        parts.append(ref_part(r))
    return parts


def photo_part(b64: str, mime: str | None, media_resolution: str | None) -> dict:
    mime = mime if mime in MIME_OK else "image/jpeg"
    p: dict = {"inline_data": {"mime_type": mime, "data": b64}}
    if media_resolution:
        p["media_resolution"] = {"level": media_resolution}
    return p


# ------------------------------------------------------------------ pass 1
def detect_schema(subtypes: list[str]) -> dict:
    return {
        "type": "object",
        "propertyOrdering": ["boxes", "store_code_on_card", "overall_confidence", "notes"],
        "properties": {
            "boxes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "propertyOrdering": ["box_2d", "label", "subtype", "format", "shelf_index", "confidence"],
                    "properties": {
                        "box_2d": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
                        "label": {"type": "string", "enum": [*BRANDS, FOREIGN]},
                        "subtype": {"type": "string", "enum": subtypes, "nullable": True},
                        "format": {"type": "string", "enum": FORMATS, "nullable": True},
                        "shelf_index": {"type": "integer"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["box_2d", "label", "subtype", "format", "shelf_index", "confidence"],
                },
            },
            "store_code_on_card": {"type": "string", "nullable": True},
            "overall_confidence": {"type": "number"},
            "notes": {"type": "string"},
        },
        "required": ["boxes", "overall_confidence"],
    }


def detect_request(refs: list[Ref], photo: dict, system_prompt: str, gen: GenConfig, ref_part: RefPartFn) -> dict:
    """refs must already be filtered (exclude_keys) and sorted (sort_refs)."""
    parts = reference_parts(refs, ref_part)
    parts.append({"text": "Теперь обведи боксами каждую единицу переднего ряда на ЭТОМ фото по правилам и схеме:"})
    parts.append(photo)
    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen.generation_config(detect_schema(subtype_enum(refs))),
    }


# ------------------------------------------------------------------ pass 2 (v9 groups)
def verify_schema(subtypes: list[str]) -> dict:
    return {
        "type": "object",
        "propertyOrdering": ["shelves"],
        "properties": {
            "shelves": {
                "type": "array",
                "items": {
                    "type": "object",
                    "propertyOrdering": ["shelf_index", "groups"],
                    "properties": {
                        "shelf_index": {"type": "integer"},
                        "groups": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "propertyOrdering": ["group_index", "subtype"],
                                "properties": {
                                    "group_index": {"type": "integer"},
                                    "subtype": {"type": "string", "enum": [*subtypes, UNKNOWN]},
                                },
                                "required": ["group_index", "subtype"],
                            },
                        },
                    },
                    "required": ["shelf_index", "groups"],
                },
            },
        },
        "required": ["shelves"],
    }


def verify_request(boxes_raw: list[dict], refs: list[Ref], photo: dict, system_prompt: str, gen: GenConfig,
                   ref_part: RefPartFn, enum_refs: list[Ref] | None = None) -> tuple[dict, list[dict]]:
    """Pass-2 body. `refs` = images to send (all 46 or the RAG top-k union);
    `enum_refs` = refs that define the schema enum (default: same as refs). A/B-1 keeps the enum full
    and changes only the images, so the experiment has one variable."""
    plan = plan_groups(boxes_raw)
    parts = reference_parts(refs, ref_part)
    parts.append({"text": "ЭТО целевое фото:"})
    parts.append(photo)
    parts.append({"text": "ПЛАН ГРУПП (границы и размеры уже проверены, счёт менять нельзя):\n" + plan_text(plan)
                  + "\n\nВерни подвид для КАЖДОЙ группы каждой полки."})
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen.generation_config(verify_schema(subtype_enum(enum_refs or refs))),
    }
    return body, plan
