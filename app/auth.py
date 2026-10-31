"""Проверка подписи данных запуска мини-приложения MAX (WebApp.initData).

Алгоритм из документации dev.max.ru/docs/webapps/validation:
secret = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)
hash   = hex(HMAC_SHA256(key=secret, msg="key=value\\n..." по алфавиту без hash))
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

from .config import BOT_TOKEN, DEV_MODE

MAX_AGE_SECONDS = 24 * 3600
DEV_USER = {"id": 1, "first_name": "Тестовый", "last_name": "Ученик", "username": "dev"}


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    pairs = parse_qsl(init_data, keep_blank_values=True)
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        return None
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash.lower()):
        return None

    auth_date = int(data.get("auth_date", "0"))
    # auth_date может прийти в секундах или миллисекундах
    if auth_date > 10**12:
        auth_date //= 1000
    if auth_date and time.time() - auth_date > MAX_AGE_SECONDS:
        return None

    user = json.loads(data.get("user", "{}"))
    data["user"] = user
    return data


def current_user(x_init_data: str = Header(default="")) -> dict:
    """FastAPI-зависимость: возвращает пользователя MAX, открывшего мини-приложение."""
    if x_init_data and BOT_TOKEN:
        data = validate_init_data(x_init_data, BOT_TOKEN)
        if data and data["user"].get("id"):
            return {**data["user"], "start_param": data.get("start_param", "")}
    if DEV_MODE:
        return {**DEV_USER, "start_param": ""}
    raise HTTPException(status_code=401, detail="Откройте приложение через бота в MAX")
