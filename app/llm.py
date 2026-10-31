"""Клиент YandexGPT (Yandex AI Studio, Foundation Models API).

Если ключ или каталог не заданы, работает заглушка — так интерфейс можно
разрабатывать и показывать без доступа к API.
"""
import json
import logging
import re

import httpx

from .config import YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_MODEL
from .http import ssl_context

log = logging.getLogger("llm")
COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0), verify=ssl_context())


class LLMUnavailable(Exception):
    """YandexGPT недоступен: нет сети, неверный ключ или ошибка сервиса."""


def enabled() -> bool:
    return bool(YANDEX_API_KEY and YANDEX_FOLDER_ID)


async def complete(system: str, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1500) -> str:
    """messages: [{"role": "user"|"assistant", "text": "..."}]"""
    if not enabled():
        return _mock(system, messages)

    body = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}",
        "completionOptions": {"stream": False, "temperature": temperature, "maxTokens": str(max_tokens)},
        "messages": [{"role": "system", "text": system}, *messages],
    }
    headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}", "x-folder-id": YANDEX_FOLDER_ID}
    try:
        resp = await _client.post(COMPLETION_URL, json=body, headers=headers)
    except httpx.HTTPError as exc:
        log.error("YandexGPT недоступен: %r", exc)
        raise LLMUnavailable from exc
    if resp.status_code >= 400:
        log.error("YandexGPT %s: %s", resp.status_code, resp.text[:500])
        raise LLMUnavailable(resp.text[:200])
    return resp.json()["result"]["alternatives"][0]["message"]["text"].strip()


async def complete_json(system: str, messages: list[dict], fallback: dict | list) -> dict | list:
    """Запрашивает ответ в JSON и аккуратно его разбирает (модель иногда добавляет ``` или текст)."""
    text = await complete(system, messages, temperature=0.2)
    match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    log.warning("Не удалось разобрать JSON от модели: %s", text[:300])
    return fallback


def _mock(system: str, messages: list[dict]) -> str:
    """Ответы-заглушки для режима без ключа."""
    if "JSON" in system and "verdict" in system:
        return json.dumps(
            {"verdict": "error", "error_type": "computational",
             "feedback": "В одном из шагов есть вычислительная ошибка. Проверь знаки при переносе слагаемых."},
            ensure_ascii=False,
        )
    if "JSON" in system and "questions" in system and "summary" not in system:
        return json.dumps(
            {"questions": [
                {"question": "Чему равен дискриминант уравнения $x^2 - 4x + 3 = 0$?",
                 "options": ["4", "16", "-4", "28"], "correct": 0,
                 "explanation": "$D = b^2 - 4ac = 16 - 12 = 4$"},
                {"question": "Сколько корней у уравнения, если $D < 0$?",
                 "options": ["Два", "Один", "Нет действительных корней", "Бесконечно много"], "correct": 2,
                 "explanation": "При отрицательном дискриминанте действительных корней нет."},
            ]},
            ensure_ascii=False,
        )
    if "JSON" in system and "summary" in system:
        return json.dumps(
            {"summary": "**Демо-режим.** Здесь появится конспект темы от YandexGPT.",
             "questions": ["Что ты уже знаешь об этой теме?", "Где она встречается на практике?"],
             "problem": "Реши уравнение $x^2 - 5x + 6 = 0$."},
            ensure_ascii=False,
        )
    if "задачу" in system and "Сгенерируй" in system:
        return "Реши уравнение $x^2 - 5x + 6 = 0$."
    return ("*(демо-режим без YandexGPT)* Хороший вопрос! А что ты уже пробовал сделать? "
            "Какой первый шаг кажется тебе логичным?")
