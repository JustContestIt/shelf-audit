"""Telegram bot of the sales agent (aiogram 3). The bot is only a channel: all logic is in the API/graph.

Flow (simplified from the n8n Main WF v9.2):
  /start -> known Telegram id? else share phone (contact button or text) -> route of the day -> store
  photo / album / image document -> POST /photos -> progress -> card with ✅ / 🔄
  ✅ -> POST /reports/{id}/review approve ;  🔄 -> next photo of this chat = retake of that report
  /store — change store (the old 15-minute TTL is replaced by an explicit command)
Env: TELEGRAM_BOT_TOKEN, API_BASE_URL, API_TOKEN.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from shelf_bot.cards import progress_text, report_card, review_keyboard, stores_keyboard

log = logging.getLogger("shelf-bot")
API = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
ALBUM_WAIT_S = 2.0
POLL_S = 3.0
MAX_WAIT_S = 600


@dataclass
class Session:
    agent: dict | None = None
    store: dict | None = None
    stores: list[dict] = field(default_factory=list)
    pending: list[tuple[str, str]] = field(default_factory=list)  # (file_id, filename) waiting for a store
    retake_for: str | None = None


sessions: dict[int, Session] = {}
albums: dict[str, list[Message]] = {}


def api() -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {os.environ['API_TOKEN']}"} if os.environ.get("API_TOKEN") else {}
    return httpx.AsyncClient(base_url=API, headers=headers, timeout=60)


def sess(uid: int) -> Session:
    return sessions.setdefault(uid, Session())


async def ensure_agent(msg: Message) -> Session | None:
    s = sess(msg.from_user.id)
    if s.agent:
        return s
    async with api() as c:
        r = await c.get(f"/agents/by-tg/{msg.from_user.id}")
    if r.status_code == 200:
        s.agent = r.json()
        return s
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
                             resize_keyboard=True, one_time_keyboard=True, is_persistent=True)
    await msg.answer("Добрый день! Чтобы начать, поделитесь номером телефона кнопкой ниже "
                     "или отправьте его текстом: +7XXXXXXXXXX", reply_markup=kb)
    return None


async def ask_store(msg: Message, s: Session, page: int = 0):
    async with api() as c:
        s.stores = (await c.get("/stores", params={"route_code": (s.agent or {}).get("route_code") or ""})).json()
    if not s.stores:
        await msg.answer("На сегодня в маршруте нет точек. Обратитесь к супервайзеру.")
        return
    await msg.answer("Выберите магазин, в котором вы сейчас:", reply_markup=stores_keyboard(s.stores, page))


dp = Dispatcher()


@dp.message(CommandStart())
async def start(msg: Message):
    s = await ensure_agent(msg)
    if s:
        await msg.answer(f"Здравствуйте, {s.agent.get('name') or s.agent['agent_id']}!", reply_markup=ReplyKeyboardRemove())
        await ask_store(msg, s)


@dp.message(Command("store"))
async def change_store(msg: Message):
    s = await ensure_agent(msg)
    if s:
        s.store = None
        await ask_store(msg, s)


@dp.message(Command("help"))
async def help_(msg: Message):
    await msg.answer("Снимайте стеллаж ближе, прямо и без вспышки; широкую витрину — серией фото по секциям. "
                     "Смена магазина — /store.")


async def _auth_phone(msg: Message, phone: str, verified: bool):
    async with api() as c:
        r = await c.post("/agents/auth", json={"phone": phone, "telegram_user_id": msg.from_user.id, "verified_contact": verified})
    if r.status_code != 200:
        await msg.answer("Номер не найден в списке агентов. Проверьте номер или обратитесь к супервайзеру.")
        return
    s = sess(msg.from_user.id)
    s.agent = r.json()
    await msg.answer("Готово, вы авторизованы.", reply_markup=ReplyKeyboardRemove())
    await ask_store(msg, s)


@dp.message(F.contact)
async def on_contact(msg: Message):
    if msg.contact.user_id and msg.contact.user_id != msg.from_user.id:
        await msg.answer("Поделитесь, пожалуйста, своим номером.")
        return
    await _auth_phone(msg, msg.contact.phone_number, True)


@dp.message(F.text.regexp(r"^\+?[78][\d\s\-()]{9,}$"))
async def on_phone_text(msg: Message):
    await _auth_phone(msg, msg.text, False)


@dp.callback_query(F.data.startswith("page:"))
async def on_page(cb: CallbackQuery):
    s = sess(cb.from_user.id)
    await cb.message.edit_reply_markup(reply_markup=stores_keyboard(s.stores, int(cb.data.split(":")[1])))
    await cb.answer()


@dp.callback_query(F.data == "noop")
async def on_noop(cb: CallbackQuery):
    await cb.answer()  # page counter: never routed to reject (BACKLOG №27 bug)


@dp.callback_query(F.data.startswith("store:"))
async def on_store(cb: CallbackQuery, bot: Bot):
    s = sess(cb.from_user.id)
    code = cb.data.split(":", 1)[1]
    s.store = next((x for x in s.stores if x["store_code"] == code), {"store_code": code, "store_name": code})
    await cb.message.edit_text(f"Магазин: <b>{s.store['store_name']}</b>. Пришлите фото полки.")
    await cb.answer()
    pending, s.pending = s.pending, []
    for i, (file_id, name) in enumerate(pending, 1):
        await process_photo(bot, cb.message, s, file_id, name, i, len(pending))


def _file_of(msg: Message) -> tuple[str, str] | None:
    if msg.photo:
        return msg.photo[-1].file_id, "photo.jpg"
    doc = msg.document
    if doc and ((doc.mime_type or "").startswith("image/") or (doc.file_name or "").lower().endswith((".jpg", ".jpeg", ".png", ".heic", ".webp"))):
        if (doc.file_size or 0) > 20 * 1024 * 1024:
            return None
        return doc.file_id, doc.file_name or "photo.jpg"
    return None


@dp.message(F.photo | F.document)
async def on_photo(msg: Message, bot: Bot):
    s = await ensure_agent(msg)
    if not s:
        return
    f = _file_of(msg)
    if f is None:
        await msg.answer("Это не фото (или файл больше 20 МБ). Пришлите фото полки.")
        return
    if msg.media_group_id:  # album: collect ~2 s, then process in order, one summary per photo
        group = albums.setdefault(msg.media_group_id, [])
        group.append(msg)
        if len(group) > 1:
            return
        await asyncio.sleep(ALBUM_WAIT_S)
        items = sorted(albums.pop(msg.media_group_id, []), key=lambda m: m.message_id)
    else:
        items = [msg]
    files = [x for x in (_file_of(m) for m in items) if x]
    if s.retake_for and len(files) == 1:
        rid, s.retake_for = s.retake_for, None
        await process_retake(bot, msg, s, rid, *files[0])
        return
    if not s.store:
        s.pending += files
        await ask_store(msg, s)
        return
    for i, (file_id, name) in enumerate(files, 1):
        await process_photo(bot, msg, s, file_id, name, i, len(files))


async def _download(bot: Bot, file_id: str) -> bytes:
    f = await bot.get_file(file_id)
    buf = await bot.download_file(f.file_path)
    return buf.read()


async def _wait_and_show(msg: Message, rid: str, status_msg: Message, index: int = 1, total: int = 1):
    async with api() as c:
        waited = 0.0
        while waited < MAX_WAIT_S:
            st = (await c.get(f"/photos/{rid}/status")).json()
            if st.get("status") in ("awaiting_review", "rejected", "failed", "approved", "edited") and not st.get("running"):
                break
            try:
                await status_msg.edit_text(progress_text(st))
            except Exception:  # noqa: BLE001 — "message is not modified"
                pass
            await asyncio.sleep(POLL_S)
            waited += POLL_S
        rep = (await c.get(f"/reports/{rid}")).json()
    kb = review_keyboard(rid) if rep.get("status") == "awaiting_review" else None
    await status_msg.edit_text(report_card(rep, index, total), reply_markup=kb)


async def process_photo(bot: Bot, msg: Message, s: Session, file_id: str, name: str, index: int = 1, total: int = 1):
    status_msg = await msg.answer("⏳ Фото обрабатывается (1–2 минуты)…")
    data = await _download(bot, file_id)
    async with api() as c:
        r = await c.post("/photos", files={"file": (name, data)},
                         data={"store_code": s.store["store_code"], "store_name": s.store["store_name"],
                               "route_code": s.store.get("route_code", ""), "agent_id": s.agent["agent_id"],
                               "chat_id": str(msg.chat.id), "source": "bot"})
    if r.status_code != 200:
        await status_msg.edit_text("⚠️ Не удалось отправить фото на обработку, попробуйте ещё раз.")
        return
    await _wait_and_show(msg, r.json()["report_id"], status_msg, index, total)


async def process_retake(bot: Bot, msg: Message, s: Session, rid: str, file_id: str, name: str):
    status_msg = await msg.answer("⏳ Пересъёмка принята, обрабатываю…")
    data = await _download(bot, file_id)
    async with api() as c:
        r = await c.post(f"/reports/{rid}/retake", files={"file": (name, data)})
    if r.status_code != 200:
        await status_msg.edit_text(f"⚠️ {r.json().get('detail', 'пересъёмка не принята')}")
        return
    await _wait_and_show(msg, rid, status_msg)


@dp.callback_query(F.data.startswith("approve:"))
async def on_approve(cb: CallbackQuery):
    rid = cb.data.split(":", 1)[1]
    s = sess(cb.from_user.id)
    async with api() as c:
        r = await c.post(f"/reports/{rid}/review", json={"action": "approve", "reviewer": (s.agent or {}).get("agent_id")})
    if r.status_code == 200:
        await cb.message.edit_text(report_card(r.json()))
        await cb.answer("Отчёт утверждён")
    else:
        await cb.answer(r.json().get("detail", "не удалось"), show_alert=True)


@dp.callback_query(F.data.startswith("retake:"))
async def on_retake(cb: CallbackQuery):
    s = sess(cb.from_user.id)
    s.retake_for = cb.data.split(":", 1)[1]
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("Пришлите новое фото этой полки: ближе, прямо, без вспышки.")
    await cb.answer()


def run():
    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set (use a NEW bot from @BotFather, not the production one)")
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    asyncio.run(dp.start_polling(bot))


if __name__ == "__main__":
    run()
