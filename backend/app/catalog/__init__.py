"""SKU taxonomy and reference images.

* taxonomy — brands, 22 canon names, formats, label background colours (in git: it is the
  schema of the task, the same enum the model sees);
* refs — reference images (studio mockups, field crops, PDF cards) described in
  data/catalog/catalog.jsonl (built by app.rag.ingest; the images themselves are not in git);
* active_refs.yaml — the 46 refs that pass 1 sends with every photo (= n8n brand_catalog).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings

CATALOG_DIR = Path(__file__).resolve().parent

BRANDS = ["Буратино", "AI TEA", "Chino", "Компотай", "Tamga"]
FOREIGN = "ЧУЖОЙ"
UNKNOWN = "НЕ ОПРЕДЕЛЁН"
FORMATS = ["банка 0,45 л", "банка 0,9 л", "ПЭТ 0,25 л", "ПЭТ 0,5 л", "ПЭТ 1 л", "ПЭТ 1,5 л", "ПЭТ 2 л", "ПЭТ 2,4 л"]
BRAND_FORMATS = {
    "AI TEA": ["банка 0,45 л", "банка 0,9 л", "ПЭТ 0,5 л", "ПЭТ 1 л"],
    "Компотай": ["банка 0,45 л", "ПЭТ 0,25 л", "ПЭТ 0,5 л", "ПЭТ 1 л", "ПЭТ 1,5 л"],
    "Буратино": ["банка 0,45 л", "ПЭТ 0,5 л", "ПЭТ 1 л", "ПЭТ 1,5 л", "ПЭТ 2 л", "ПЭТ 2,4 л"],
    "Chino": [],
    "Tamga": [],
}

# key -> (brand, canon name, label background colour); colours from the v7.5-bgcolor prompt
SKUS: dict[str, tuple[str, str, str | None]] = {
    "buratino_klassicheskiy": ("Буратино", "Буратино классический", None),
    "buratino_dynya_myata": ("Буратино", "Буратино дыня-мята", None),
    "buratino_granat": ("Буратино", "Буратино гранат", None),
    "aitea_malina": ("AI TEA", "AI TEA малина", "фиолетовый"),
    "aitea_guava_tropiki": ("AI TEA", "AI TEA гуава-тропики", "зелёный"),
    "aitea_mandarin_lavanda": ("AI TEA", "AI TEA мандарин-лаванда", "оранжевый"),
    "aitea_reven": ("AI TEA", "AI TEA ревень", "розовый"),
    "aitea_pomelo": ("AI TEA", "AI TEA помело-цветок апельсина", "зелёный"),
    "aitea_mango_marakuya": ("AI TEA", "AI TEA манго-маракуйя", "оранжевый"),
    "aitea_klubnika_kivi": ("AI TEA", "AI TEA клубника-киви", "малиновый"),
    "aitea_limon_laim_zhasmin": ("AI TEA", "AI TEA лимон-лайм-жасмин", "жёлтый"),
    "aitea_persik_zhasmin": ("AI TEA", "AI TEA персик-жасмин", "розовый"),
    "chino_bellini": ("Chino", "Chino Bellini", None),
    "chino_rossini": ("Chino", "Chino Rossini", None),
    "chino_tintoretto": ("Chino", "Chino Tintoretto", None),
    "chino_mimosa": ("Chino", "Chino Mimosa", None),
    "kompotay_yagodny": ("Компотай", "Компотай ягодный", None),
    "kompotay_granatovy": ("Компотай", "Компотай гранатовый", None),
    "kompotay_slivovy": ("Компотай", "Компотай сливовый", None),
    "kompotay_vishnevy": ("Компотай", "Компотай вишневый", None),
    "kompotay_klassicheskiy": ("Компотай", "Компотай классический", None),
    "tamga": ("Tamga", "Tamga", None),
}
CANON_TO_KEY = {v[1]: k for k, v in SKUS.items()}
SHORT_NAMES = {  # short Russian names used by the old scorers / GT files
    "помело": "AI TEA помело-цветок апельсина", "манго": "AI TEA манго-маракуйя", "клубника": "AI TEA клубника-киви",
    "лимон": "AI TEA лимон-лайм-жасмин", "малина": "AI TEA малина", "персик": "AI TEA персик-жасмин",
    "мандарин": "AI TEA мандарин-лаванда", "гуава": "AI TEA гуава-тропики", "ревень": "AI TEA ревень",
}


def canon(name: str | None) -> str | None:
    """Accept a canon name, a short name ('малина') or a name without brand ('малина', 'помело-цветок апельсина')."""
    if not name:
        return None
    n = name.strip().rstrip("?")
    if n in CANON_TO_KEY:
        return n
    if n in SHORT_NAMES:
        return SHORT_NAMES[n]
    if "AI TEA " + n in CANON_TO_KEY:
        return "AI TEA " + n
    return n


def base_key(key: str) -> str:
    return key.split("__", 1)[0]


# ------------------------------------------------------------ ICU-like ru collation
def _char_key(ch: str) -> tuple[int, int]:
    c = ch.lower()
    if c == "ё":
        return (2, ord("е") * 2 + 1)
    if "а" <= c <= "я":
        return (2, ord(c) * 2)
    if "a" <= c <= "z":
        return (3, ord(c))
    if c.isdigit():
        return (1, ord(c))
    return (0, ord(c))  # spaces, '_', '-', punctuation sort first (ICU non-ignorable)


def ru_key(s: str) -> tuple:
    """Approximation of JS localeCompare(…, 'ru') for our names: Cyrillic before Latin."""
    s = unicodedata.normalize("NFC", str(s))
    return tuple(_char_key(ch) for ch in s)


# ------------------------------------------------------------ reference images
@dataclass
class Ref:
    key: str                     # e.g. aitea_klubnika_kivi__pet05_ru
    brand: str
    canon_name: str
    variant: str | None = None   # suffix after "__"
    pack: str | None = None      # банка 0,45 л / ПЭТ 1 л / ... when known from the name
    lang: str | None = None      # ru / kz
    source: str = "studio"       # studio | field | pdf
    path: str | None = None      # relative to data/catalog
    mime_type: str = "image/jpeg"
    extra: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


PACK_TOKENS = [
    (re.compile(r"(^|_)can900"), "банка 0,9 л"),
    (re.compile(r"(^|_)can045|(^|_)can($|_)"), "банка 0,45 л"),
    (re.compile(r"(^|_)pet05|pet045"), "ПЭТ 0,5 л"),
    (re.compile(r"(^|_)pet025"), "ПЭТ 0,25 л"),
    (re.compile(r"(^|_)pet1000|(^|_)pet1($|_)|sleever"), "ПЭТ 1 л"),
    (re.compile(r"(^|_)pet15"), "ПЭТ 1,5 л"),
    (re.compile(r"(^|_)pet24"), "ПЭТ 2,4 л"),
    (re.compile(r"(^|_)pet2($|_)"), "ПЭТ 2 л"),
]


def parse_ref_name(stem: str) -> dict:
    """'aitea_klubnika_kivi__pet05_ru' -> key/base/variant/pack/lang (grammar of README_ALL)."""
    key = stem.replace("__FIELD_", "__field_").replace("_FIELD_", "_field_")
    base, _, variant = key.partition("__")
    v = variant.lower() or None
    pack = next((p for rx, p in PACK_TOKENS if v and rx.search(v)), None)
    lang = "kz" if v and re.search(r"(^|_)kz($|_)", v) else "ru" if v and re.search(r"(^|_)ru($|_)", v) else None
    return {"key": key, "base": base, "variant": v, "pack": pack, "lang": lang,
            "source": "field" if v and "field" in v else "studio"}


@lru_cache
def load_catalog(path: str | None = None) -> list[Ref]:
    p = Path(path) if path else get_settings().catalog_path
    if not p.exists():
        return []
    refs = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            refs.append(Ref(**{k: d.get(k) for k in Ref.__dataclass_fields__ if k in d}))
    return refs


@lru_cache
def load_active_refs(path: str | None = None) -> list[Ref]:
    """The pass-1 reference set (46 rows = n8n `brand_catalog` minus excluded keys at request time)."""
    p = Path(path) if path else get_settings().active_refs_path
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    out = []
    for row in data["refs"]:
        brand, canon_name, _ = SKUS[base_key(row["key"])]
        out.append(Ref(key=row["key"], brand=brand, canon_name=canon_name, variant=row.get("variant"),
                       pack=row.get("pack"), source=row.get("source", "studio"), path=row["path"],
                       mime_type=row.get("mime_type", "image/jpeg")))
    return out


def is_excluded(key: str, exclude_keys: list[str]) -> bool:
    return any(key == p or key.startswith(p + "__") for p in exclude_keys)


def subtype_enum(refs: list[Ref]) -> list[str]:
    """Unique canon names in prompt order, Tamga excluded (no subtypes) — schema enum of pass 1/2."""
    seen, out = set(), []
    for r in refs:
        if r.canon_name not in seen:
            seen.add(r.canon_name)
            out.append(r.canon_name)
    return [c for c in out if c != "Tamga"]


def sort_refs(refs: list[Ref]) -> list[Ref]:
    """Stable prompt order: brand -> canon name -> key (implicit cache wants a byte-identical prefix)."""
    return sorted(refs, key=lambda r: (ru_key(r.brand), ru_key(r.canon_name), ru_key(r.key)))
