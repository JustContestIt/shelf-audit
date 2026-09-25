"""Texts and keyboards of the bot (pure functions — unit-tested without Telegram)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PAGE = 8
STATUS_LINE = {"approved": "✅ Утверждено", "edited": "✏️ Исправлено супервайзером", "rejected": "⛔ Фото отклонено",
               "failed": "⚠️ Не удалось обработать"}


def _sub(row: dict) -> str:
    s = row.get("subtype")
    if s:
        return s.removeprefix(row["brand"]).strip() or s
    return "—" if row["brand"] == "Tamga" else "не опознано"


def report_card(rep: dict, index: int | None = None, total: int | None = None) -> str:
    """Card after a photo: counts by shelf; rows to check are marked and not counted as final."""
    body = rep.get("body") or {}
    r = body.get("report") or {}
    head = f"📷 Фото {index}/{total}" if index and total and total > 1 else "📷 Отчёт по фото"
    lines = [f"<b>{head}</b> · {rep.get('store_name') or rep.get('store_code') or 'магазин не выбран'}"]
    if rep.get("status") == "rejected":
        lines.append(f"⛔ {rep.get('reject_reason') or 'фото не подходит'}")
        lines.append("Переснимите: ближе, прямо, без вспышки — стеллаж на весь кадр.")
        return "\n".join(lines)
    rows = r.get("rows") or []
    if not rows:
        lines.append("Наш товар на фото не найден. Если он есть — переснимите ближе.")
    by_shelf: dict[int, list[dict]] = {}
    for x in rows:
        by_shelf.setdefault(x["shelf_index"], []).append(x)
    for shelf in sorted(by_shelf):
        lines.append(f"\n<b>Полка {shelf}</b>")
        for x in by_shelf[shelf]:
            mark = " ⚠️" if x.get("needs_review") else ""
            pack = f", {x['package_format']}" if x.get("package_format") else ""
            lines.append(f"• {x['brand']} {_sub(x)}{pack} — <b>{x['front_facing_count']}</b>{mark}")
    total_units = r.get("total_units") or 0
    lines.append(f"\nВсего наших единиц: <b>{total_units}</b>")
    if r.get("needs_review_units"):
        lines.append(f"⚠️ На проверке у супервайзера: {r['needs_review_units']} ед.")
    if r.get("foreign_units"):
        lines.append(f"Чужой товар рядом (не в счёте): {r['foreign_units']} ед.")
    if r.get("low_confidence"):
        lines.append("Фото нечёткое или снято издалека — сверьте счёт; если неверно, нажмите «Переснять».")
    st = STATUS_LINE.get(rep.get("status") or "")
    if st:
        lines.append(f"\n{st}")
    else:
        lines.append("\nСверьте счёт с полкой: всё верно?")
    return "\n".join(lines)


def review_keyboard(report_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Всё верно", callback_data=f"approve:{report_id}"),
        InlineKeyboardButton(text="🔄 Переснять", callback_data=f"retake:{report_id}"),
    ]])


def stores_keyboard(stores: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    """Route of the day (≤ 30 stores), 8 per page; button = name + address (one route often has several stores of the same chain)."""
    pages = max(1, (len(stores) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = [[InlineKeyboardButton(text=f"{s['store_name']} · {s.get('address', '')}".strip(" ·")[:60],
                                  callback_data=f"store:{s['store_code']}")]
            for s in stores[page * PAGE:(page + 1) * PAGE]]
    if pages > 1:
        rows.append([
            InlineKeyboardButton(text="◀️", callback_data=f"page:{page - 1}" if page > 0 else "noop"),
            InlineKeyboardButton(text=f"{page + 1} / {pages}", callback_data="noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"page:{page + 1}" if page < pages - 1 else "noop"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


PROGRESS_RU = {"validate_input": "проверяю фото", "input_guard": "проверяю фото", "detect": "ищу товар на полках",
               "postprocess": "считаю", "retrieve_refs": "сверяю с эталонами", "verify_subtypes": "уточняю вкусы",
               "build_report": "собираю отчёт"}


def progress_text(status: dict) -> str:
    prog = status.get("progress") or []
    last = prog[-1]["node"] if prog else None
    return "⏳ " + (PROGRESS_RU.get(last, "в очереди") if last else "в очереди") + "…"
