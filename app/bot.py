"""Чат-бот MAX: приветствие, кнопка открытия мини-приложения и короткие ответы в чате."""
import asyncio
import logging

import httpx

from . import llm, tutor
from .db import upsert_user
from .max_api import MaxApi

log = logging.getLogger("bot")

WELCOME = (
    "Привет, {name}! Я **СОКРАТ** — ИИ-наставник по математике.\n\n"
    "Я не решаю задачи за тебя. Я задаю вопросы, которые помогают дойти до ответа самому, "
    "проверяю решения, показываю тип ошибки и собираю тесты из твоих личных ошибок.\n\n"
    "Нажми «Открыть», чтобы начать."
)


LLM_DOWN = "Извини, ИИ-наставник сейчас недоступен. Попробуй ещё раз через минуту 🙏"

# Данные бота из GET /me: нужны для кнопки open_app (web_app = имя бота, contact_id = его id)
BOT_INFO: dict = {}


def open_app_keyboard() -> list[list[dict]] | None:
    if not BOT_INFO.get("username"):
        return None
    return [[{"type": "open_app", "text": "Открыть СОКРАТ",
              "web_app": BOT_INFO["username"], "contact_id": BOT_INFO["user_id"]}]]


async def send_with_app_button(api: MaxApi, target: dict, text: str) -> None:
    try:
        await api.send_message(**target, text=text, buttons=open_app_keyboard())
    except httpx.HTTPStatusError:
        # Если мини-приложение ещё не привязано к боту, кнопка open_app недоступна — шлём без неё
        await api.send_message(**target, text=text)


async def send_welcome(api: MaxApi, user: dict, chat_id: int | None) -> None:
    text = WELCOME.format(name=user.get("first_name") or "друг")
    target = {"chat_id": chat_id} if chat_id else {"user_id": user["user_id"]}
    await send_with_app_button(api, target, text)


async def handle_update(api: MaxApi, update: dict) -> None:
    kind = update.get("update_type")
    if kind == "bot_started":
        user = update["user"]
        upsert_user({"id": user["user_id"], "first_name": user.get("first_name"), "last_name": user.get("last_name")})
        await send_welcome(api, user, update.get("chat_id"))
        return

    if kind == "message_created":
        message = update["message"]
        sender = message.get("sender") or {}
        if not sender or sender.get("is_bot"):
            return
        text = (message.get("body") or {}).get("text") or ""
        chat_id = (message.get("recipient") or {}).get("chat_id")
        if text.strip().lower() in ("/start", "start", "старт", "начать"):
            await send_welcome(api, sender, chat_id)
            return
        # Быстрый вопрос прямо в чате: отвечаем в сократическом стиле, без готового ответа
        user = upsert_user({"id": sender["user_id"], "first_name": sender.get("first_name"),
                            "last_name": sender.get("last_name")})
        try:
            answer = await tutor.reply(user, "вопрос из чата", None, [{"role": "user", "text": text}], [])
        except llm.LLMUnavailable:
            await api.send_message(chat_id=chat_id, text=LLM_DOWN)
            return
        await send_with_app_button(
            api, {"chat_id": chat_id},
            answer + "\n\n_Чтобы разобрать задачу до конца и следить за прогрессом, открой приложение._",
        )


async def load_bot_info(api: MaxApi) -> None:
    try:
        BOT_INFO.update(await api.me())
        log.info("Бот: @%s (id %s)", BOT_INFO.get("username"), BOT_INFO.get("user_id"))
    except Exception as exc:
        log.warning("Не удалось получить данные бота: %s", exc)


async def run_polling(api: MaxApi) -> None:
    marker = None
    log.info("Бот MAX запущен в режиме long polling")
    while not BOT_INFO:
        await load_bot_info(api)
        if not BOT_INFO:
            await asyncio.sleep(5)
    while True:
        try:
            data = await api.get_updates(marker)
            marker = data.get("marker", marker)
            for update in data.get("updates", []):
                try:
                    await handle_update(api, update)
                except Exception:
                    log.exception("Ошибка обработки обновления %s", update.get("update_type"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Ошибка получения обновлений: %s", exc)
            await asyncio.sleep(5)
