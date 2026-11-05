"""Веб-версия СОКРАТа: рабочее место ученика — чат с наставником, темы, проверка, тест и прогресс.

Всё делается через tutor.py — тот же «мозг», что и у бота, поэтому прогресс общий.
Войти можно двумя способами:
  1. Внутри MAX (мини-приложение): MAX передаёт подписанные данные initData, мы проверяем подпись.
  2. В браузере: бот по кнопке «🌐 Веб-кабинет» присылает одноразовый код, ученик вводит его на сайте.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import db
import tutor
from ai import ERROR_TYPES, GOALS

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
STATIC = Path(__file__).parent / "static"
MAX_PHOTO = 8 * 1024 * 1024        # фото больше 8 МБ не принимаем
INIT_DATA_MAX_AGE = 24 * 3600      # сколько действуют данные запуска мини-приложения

app = FastAPI(title="СОКРАТ — веб-версия")


@app.exception_handler(tutor.TutorError)
def tutor_error(request: Request, exc: tutor.TutorError):
    """Понятные ученику ситуации («подсказки кончились») — показываем текстом, а не ошибкой сервера."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------- вход ----------

def sign(user_id: int) -> str:
    """Токен сессии: id ученика + подпись токеном бота. Подделать без токена бота нельзя."""
    signature = hmac.new(BOT_TOKEN.encode(), f"web:{user_id}".encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{signature}"


def user_from_token(token: str) -> int | None:
    user_id, _, _ = token.partition(".")
    if not user_id.isdigit():
        return None
    return int(user_id) if hmac.compare_digest(sign(int(user_id)), token) else None


def user_from_init_data(init_data: str) -> int | None:
    """Проверка подписи данных мини-приложения MAX (алгоритм из dev.max.ru/docs/webapps/validation)."""
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received = data.pop("hash", "")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(expected, received):
        return None
    # Подписанные данные действуют сутки: без даты или старше — не принимаем,
    # иначе однажды утёкшая ссылка запуска работала бы вечно
    auth_date = data.get("auth_date", "")
    if not auth_date.isdigit():
        return None
    auth_date = int(auth_date)
    if auth_date > 10**12:                      # MAX может прислать время в миллисекундах
        auth_date //= 1000
    if not 0 <= time.time() - auth_date <= INIT_DATA_MAX_AGE:
        return None
    return json.loads(data.get("user", "{}")).get("id")


def current_user_id(authorization: str = Header(default=""), x_init_data: str = Header(default="")) -> int:
    """Кто открыл сайт. Если не удалось определить — ошибка 401, страница покажет вход по коду."""
    user_id = None
    if x_init_data:
        user_id = user_from_init_data(x_init_data)
    if user_id is None and authorization.startswith("Bearer "):
        user_id = user_from_token(authorization.removeprefix("Bearer "))
    if user_id is None:
        raise HTTPException(401, "Нужен вход")
    return user_id


def load_user(session, user_id):
    user = session.get(db.User, user_id)
    if user is None:
        raise HTTPException(404, "Сначала напиши боту в MAX")
    return user


class CodeIn(BaseModel):
    code: str


@app.post("/api/login")
def login(body: CodeIn):
    with Session(db.engine) as session:
        user = db.user_by_code(session, body.code.strip())
        if user is None:
            raise HTTPException(400, "Код неверный или устарел. Получи новый в боте.")
        session.commit()
        return {"token": sign(user.id)}


# ---------- профиль и прогресс ----------

class ProfileIn(BaseModel):
    grade: int = Field(ge=5, le=11)
    goal: str


@app.get("/api/me")
def me(user_id: int = Depends(current_user_id)):
    with Session(db.engine) as session:
        user = load_user(session, user_id)
        stats = db.independence(session, user)
        return {
            "name": user.name,
            "grade": user.grade,
            "goal": user.goal,
            "goals": GOALS,
            "current_space_id": user.current_space_id,
            "index": stats["index"],
            "solved": stats["solved"],
            "first_try": stats["first_try"],
            "history": stats["history"],
            "mistakes": [{"type": ERROR_TYPES.get(t, t), "count": n}
                         for t, n in sorted(stats["mistake_types"].items(), key=lambda x: -x[1])],
            "spaces": [{"id": s.id, "topic": s.topic, "created": s.created_at.strftime("%d.%m"),
                        **db.space_stats(session, s)}
                       for s in db.list_spaces(session, user, limit=30) if s.topic != tutor.FREE_TOPIC],
            "quizzes": [{"date": q.created_at.strftime("%d.%m %H:%M"), "score": q.score,
                         "total": len(json.loads(q.questions))} for q in db.quiz_history(session, user)],
        }


@app.put("/api/me")
def update_profile(body: ProfileIn, user_id: int = Depends(current_user_id)):
    if body.goal not in GOALS:
        raise HTTPException(400, "Неизвестная цель")
    with Session(db.engine) as session:
        user = load_user(session, user_id)
        user.grade, user.goal = body.grade, body.goal
        session.commit()
    return {"ok": True}


# ---------- темы и чат ----------

class TopicIn(BaseModel):
    topic: str = Field(min_length=2, max_length=200)


class MessageIn(BaseModel):
    text: str = Field(default="", max_length=4000)
    photo: str = ""            # картинка в base64 (необязательно)
    check: bool = False        # True — это решение на проверку


def space_view(session, space) -> dict:
    return {"id": space.id, "topic": space.topic, "hints": space.hints, "max_hints": tutor.MAX_HINTS,
            "messages": [{"role": m.role, "text": m.content} for m in space.messages]}


def decode_photo(photo: str) -> bytes | None:
    if not photo:
        return None
    try:
        data = base64.b64decode(photo.split(",")[-1])     # «data:image/png;base64,…» или чистый base64
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Не удалось прочитать фото")
    if len(data) > MAX_PHOTO:
        raise HTTPException(400, "Фото слишком большое — максимум 8 МБ")
    return data


@app.post("/api/spaces")
def create_space(body: TopicIn, user_id: int = Depends(current_user_id)):
    with Session(db.engine) as session:
        user = load_user(session, user_id)
        space, _ = tutor.open_topic(session, user, body.topic)
        return space_view(session, space)


@app.get("/api/spaces/{space_id}")
def open_space(space_id: int, user_id: int = Depends(current_user_id)):
    with Session(db.engine) as session:
        user = load_user(session, user_id)
        space = tutor.switch_space(session, user, space_id)       # чужую тему открыть нельзя
        return space_view(session, space)


@app.post("/api/spaces/{space_id}/messages")
def send_message(space_id: int, body: MessageIn, user_id: int = Depends(current_user_id)):
    photo = decode_photo(body.photo)
    if not body.text.strip() and not photo:
        raise HTTPException(400, "Пустое сообщение")
    with Session(db.engine) as session:
        user = load_user(session, user_id)
        tutor.switch_space(session, user, space_id)
        if body.check:
            result = tutor.check(session, user, body.text, photo)
        else:
            result = tutor.reply(session, user, body.text, photo)
        return {**space_view(session, result["space"]), "verdict": result.get("verdict")}


@app.post("/api/spaces/{space_id}/hint")
def get_hint(space_id: int, user_id: int = Depends(current_user_id)):
    with Session(db.engine) as session:
        user = load_user(session, user_id)
        tutor.switch_space(session, user, space_id)
        result = tutor.hint(session, user)
        return space_view(session, result["space"])


@app.post("/api/spaces/{space_id}/next")
def get_next_task(space_id: int, user_id: int = Depends(current_user_id)):
    with Session(db.engine) as session:
        user = load_user(session, user_id)
        tutor.switch_space(session, user, space_id)
        result = tutor.next_task(session, user)
        return space_view(session, result["space"])


# ---------- тест по ошибкам ----------

class AnswerIn(BaseModel):
    index: int
    option: int


@app.post("/api/quiz")
def create_quiz(user_id: int = Depends(current_user_id)):
    with Session(db.engine) as session:
        user = load_user(session, user_id)
        quiz = tutor.create_quiz(session, user)
        return {"id": quiz.id, "questions": tutor.public_questions(quiz)}


@app.post("/api/quiz/{quiz_id}/answer")
def answer_quiz(quiz_id: int, body: AnswerIn, user_id: int = Depends(current_user_id)):
    with Session(db.engine) as session:
        user = load_user(session, user_id)
        result = tutor.answer_quiz(session, user, quiz_id, body.index, body.option)
        if result is None:
            raise HTTPException(400, "На этот вопрос уже ответили")
        result.pop("quiz")
        return result


# ---------- страница ----------

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
