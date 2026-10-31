"""СОКРАТ: веб-сервер мини-приложения, API и запуск бота MAX."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import bot, llm, tutor
from .auth import current_user
from .config import BOT_MODE, BOT_TOKEN, DEV_MODE, PUBLIC_URL, WEBAPP_DIR
from .db import connect, dumps, init_db, row, rows, upsert_user
from .max_api import MaxApi

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sokrat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.api = MaxApi() if BOT_TOKEN else None
    task = None
    if app.state.api:
        if BOT_MODE == "webhook" and PUBLIC_URL:
            await app.state.api.subscribe_webhook(f"{PUBLIC_URL}/max/webhook")
            log.info("Вебхук MAX: %s/max/webhook", PUBLIC_URL)
        else:
            task = asyncio.create_task(bot.run_polling(app.state.api))
    else:
        log.warning("BOT_TOKEN не задан — бот не запущен, работает только мини-приложение")
    if not llm.enabled():
        log.warning("YANDEX_API_KEY / YANDEX_FOLDER_ID не заданы — ИИ работает в демо-режиме")
    yield
    if task:
        task.cancel()
    if app.state.api:
        await app.state.api.close()


app = FastAPI(title="СОКРАТ", lifespan=lifespan)


@app.exception_handler(llm.LLMUnavailable)
async def llm_unavailable(request: Request, exc: llm.LLMUnavailable):
    return JSONResponse(status_code=503, content={"detail": "ИИ-наставник сейчас недоступен, попробуй через минуту"})


# ---------- модели запросов ----------

class TopicIn(BaseModel):
    topic: str = Field(min_length=2, max_length=120)


class TextIn(BaseModel):
    text: str = Field(default="", max_length=4000)


class ProfileIn(BaseModel):
    grade: int | None = Field(default=None, ge=1, le=11)


class QuizAnswersIn(BaseModel):
    answers: list[int]


# ---------- вспомогательные функции ----------

def db_user(user: dict) -> dict:
    return upsert_user(user)


def get_space(db, space_id: int, user_id: int) -> dict:
    space = row(db.execute("SELECT * FROM spaces WHERE id=? AND user_id=?", (space_id, user_id)))
    if not space:
        raise HTTPException(404, "Пространство не найдено")
    return space


def active_problem(db, space_id: int) -> dict | None:
    return row(db.execute(
        "SELECT * FROM problems WHERE space_id=? AND status='active' ORDER BY id DESC LIMIT 1", (space_id,)))


def history(db, space_id: int, problem_id: int | None) -> list[dict]:
    msgs = rows(db.execute(
        "SELECT role, text FROM messages WHERE space_id=? AND problem_id IS ? AND kind IN ('chat','hint','check') "
        "ORDER BY id", (space_id, problem_id)))
    return [{"role": m["role"], "text": m["text"]} for m in msgs]


def user_mistakes(db, user_id: int, unresolved_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM mistakes WHERE user_id=?" + (" AND resolved=0" if unresolved_only else "")
    return rows(db.execute(sql + " ORDER BY id DESC LIMIT 30", (user_id,)))


def add_message(db, space_id: int, problem_id: int | None, role: str, kind: str, text: str) -> dict:
    cur = db.execute("INSERT INTO messages (space_id, problem_id, role, kind, text) VALUES (?,?,?,?,?)",
                     (space_id, problem_id, role, kind, text))
    return row(db.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)))


def create_problem(db, space_id: int, text: str) -> dict:
    cur = db.execute("INSERT INTO problems (space_id, text) VALUES (?, ?)", (space_id, text))
    add_message(db, space_id, cur.lastrowid, "assistant", "problem", text)
    return row(db.execute("SELECT * FROM problems WHERE id=?", (cur.lastrowid,)))


def stats(db, user_id: int, space_id: int | None = None) -> dict:
    where, args = "s.user_id=?", [user_id]
    if space_id:
        where, args = where + " AND s.id=?", args + [space_id]
    finished = rows(db.execute(
        f"SELECT p.score, p.status, p.hint_level FROM problems p JOIN spaces s ON s.id=p.space_id "
        f"WHERE {where} AND p.status IN ('solved','given_up')", args))
    return {
        "index": tutor.independence_index([p["score"] or 0 for p in finished]),
        "solved": sum(p["status"] == "solved" for p in finished),
        "solo": sum(p["status"] == "solved" and p["hint_level"] == 0 for p in finished),
        "total": len(finished),
    }


# ---------- API: профиль ----------

@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    u = db_user(user)
    with connect() as db:
        mistakes = user_mistakes(db, u["id"], unresolved_only=False)
        by_type: dict[str, int] = {}
        by_topic: dict[str, int] = {}
        for m in mistakes:
            if not m["resolved"]:
                by_type[m["error_type"]] = by_type.get(m["error_type"], 0) + 1
                by_topic[m["topic"]] = by_topic.get(m["topic"], 0) + 1
        return {
            "user": u,
            "stats": stats(db, u["id"]),
            "mistakes_by_type": [{"type": k, "label": tutor.ERROR_TYPES.get(k, k), "count": v}
                                 for k, v in sorted(by_type.items(), key=lambda x: -x[1])],
            "weak_topics": [{"topic": k, "count": v} for k, v in sorted(by_topic.items(), key=lambda x: -x[1])][:5],
            "open_mistakes": sum(by_type.values()),
            "start_param": user.get("start_param", ""),
            "ai_enabled": llm.enabled(),
        }


@app.patch("/api/me")
def update_me(body: ProfileIn, user: dict = Depends(current_user)):
    db_user(user)
    with connect() as db:
        db.execute("UPDATE users SET grade=? WHERE id=?", (body.grade, user["id"]))
    return {"ok": True}


# ---------- API: пространства ----------

@app.get("/api/spaces")
def list_spaces(user: dict = Depends(current_user)):
    db_user(user)
    with connect() as db:
        spaces = rows(db.execute("SELECT id, topic, created_at FROM spaces WHERE user_id=? ORDER BY id DESC",
                                 (user["id"],)))
        for s in spaces:
            s["stats"] = stats(db, user["id"], s["id"])
        return spaces


@app.post("/api/spaces")
async def create_space(body: TopicIn, user: dict = Depends(current_user)):
    u = db_user(user)
    intro = await tutor.space_intro(u, body.topic.strip())
    summary = intro["summary"]
    if intro["questions"]:
        summary += "\n\n**Проверь себя:**\n" + "\n".join(f"- {q}" for q in intro["questions"])
    with connect() as db:
        cur = db.execute("INSERT INTO spaces (user_id, topic, summary) VALUES (?,?,?)",
                         (u["id"], body.topic.strip(), summary))
        if intro["problem"]:
            create_problem(db, cur.lastrowid, intro["problem"])
        return {"id": cur.lastrowid}


@app.get("/api/spaces/{space_id}")
def get_space_full(space_id: int, user: dict = Depends(current_user)):
    with connect() as db:
        space = get_space(db, space_id, user["id"])
        messages = rows(db.execute(
            "SELECT id, problem_id, role, kind, text, created_at FROM messages WHERE space_id=? ORDER BY id",
            (space_id,)))
        return {"space": space, "problem": active_problem(db, space_id), "messages": messages,
                "stats": stats(db, user["id"], space_id)}


@app.delete("/api/spaces/{space_id}")
def delete_space(space_id: int, user: dict = Depends(current_user)):
    with connect() as db:
        get_space(db, space_id, user["id"])
        for table in ("messages", "problems"):
            db.execute(f"DELETE FROM {table} WHERE space_id=?", (space_id,))
        db.execute("DELETE FROM spaces WHERE id=?", (space_id,))
    return {"ok": True}


@app.post("/api/spaces/{space_id}/messages")
async def send_message(space_id: int, body: TextIn, user: dict = Depends(current_user)):
    u = db_user(user)
    if not body.text.strip():
        raise HTTPException(400, "Пустое сообщение")
    with connect() as db:
        space = get_space(db, space_id, u["id"])
        problem = active_problem(db, space_id)
        pid = problem["id"] if problem else None
        mine = add_message(db, space_id, pid, "user", "chat", body.text.strip())
        hist = history(db, space_id, pid)
        mistakes = user_mistakes(db, u["id"])
    answer = await tutor.reply(u, space["topic"], problem["text"] if problem else None, hist, mistakes)
    with connect() as db:
        theirs = add_message(db, space_id, pid, "assistant", "chat", answer)
    return {"messages": [mine, theirs]}


@app.post("/api/spaces/{space_id}/problem")
async def new_problem(space_id: int, body: TextIn, user: dict = Depends(current_user)):
    """Новая задача: своя (text) или сгенерированная. Незавершённая задача засчитывается как брошенная."""
    u = db_user(user)
    with connect() as db:
        space = get_space(db, space_id, u["id"])
        old = active_problem(db, space_id)
        if old:
            touched = db.execute("SELECT COUNT(*) FROM messages WHERE problem_id=? AND role='user'",
                                 (old["id"],)).fetchone()[0]
            if touched or old["hint_level"]:
                db.execute("UPDATE problems SET status='given_up', score=0 WHERE id=?", (old["id"],))
            else:
                db.execute("DELETE FROM messages WHERE problem_id=?", (old["id"],))
                db.execute("DELETE FROM problems WHERE id=?", (old["id"],))
        mistakes = [m for m in user_mistakes(db, u["id"]) if m["space_id"] == space_id]
    text = body.text.strip() or await tutor.new_problem(u, space["topic"], mistakes)
    with connect() as db:
        problem = create_problem(db, space_id, text)
    return {"problem": problem}


@app.post("/api/spaces/{space_id}/hint")
async def get_hint(space_id: int, user: dict = Depends(current_user)):
    u = db_user(user)
    with connect() as db:
        space = get_space(db, space_id, u["id"])
        problem = active_problem(db, space_id)
        if not problem:
            raise HTTPException(400, "Сначала выбери задачу")
        level = min(problem["hint_level"] + 1, 4)
        hist = history(db, space_id, problem["id"])
    text = await tutor.hint(u, space["topic"], problem["text"], level, hist)
    with connect() as db:
        db.execute("UPDATE problems SET hint_level=? WHERE id=?", (level, problem["id"]))
        msg = add_message(db, space_id, problem["id"], "assistant", "hint",
                          f"**Подсказка {level}/4 · {tutor.HINT_LEVELS[level]}**\n\n{text}")
    return {"message": msg, "hint_level": level}


@app.post("/api/spaces/{space_id}/check")
async def check(space_id: int, body: TextIn, user: dict = Depends(current_user)):
    u = db_user(user)
    if not body.text.strip():
        raise HTTPException(400, "Напиши решение")
    with connect() as db:
        space = get_space(db, space_id, u["id"])
        problem = active_problem(db, space_id)
        if not problem:
            raise HTTPException(400, "Сначала выбери задачу")
        mine = add_message(db, space_id, problem["id"], "user", "check", f"**Моё решение:**\n{body.text.strip()}")
    result = await tutor.check_solution(u, space["topic"], problem["text"], body.text.strip())
    checks = problem["checks"] + 1
    solved = result["verdict"] == "correct"
    with connect() as db:
        if solved:
            score = tutor.problem_score(problem["hint_level"], checks, True)
            db.execute("UPDATE problems SET checks=?, status='solved', score=?, solved_at=CURRENT_TIMESTAMP "
                       "WHERE id=?", (checks, score, problem["id"]))
            text = f"✅ **Верно!** {result['feedback']}"
        else:
            db.execute("UPDATE problems SET checks=? WHERE id=?", (checks, problem["id"]))
            db.execute("INSERT INTO mistakes (user_id, space_id, problem_id, topic, error_type, description) "
                       "VALUES (?,?,?,?,?,?)",
                       (u["id"], space_id, problem["id"], space["topic"], result["error_type"] or "incomplete",
                        result.get("step") or result["feedback"]))
            label = result["error_label"] or "Есть неточность"
            where = f"\n\n🔎 Где искать: {result['step']}" if result.get("step") else ""
            text = f"⚠️ **{label}.** {result['feedback']}{where}"
        theirs = add_message(db, space_id, problem["id"], "assistant", "check", text)
        return {"messages": [mine, theirs], "verdict": result["verdict"], "stats": stats(db, u["id"], space_id)}


# ---------- API: тест по личным ошибкам ----------

@app.post("/api/quiz")
async def create_quiz(user: dict = Depends(current_user)):
    u = db_user(user)
    with connect() as db:
        mistakes = user_mistakes(db, u["id"])
        topics = [r["topic"] for r in rows(db.execute("SELECT DISTINCT topic FROM spaces WHERE user_id=?", (u["id"],)))]
    if not mistakes and not topics:
        raise HTTPException(400, "Сначала порешай задачи — тест собирается из твоих ошибок")
    questions = await tutor.mistakes_quiz(u, mistakes, topics)
    if not questions:
        raise HTTPException(502, "Не получилось составить тест, попробуй ещё раз")
    with connect() as db:
        cur = db.execute("INSERT INTO quizzes (user_id, questions) VALUES (?, ?)",
                         (u["id"], dumps({"questions": questions, "mistake_ids": [m["id"] for m in mistakes[:10]]})))
    public = [{"question": q["question"], "options": q["options"]} for q in questions]
    return {"id": cur.lastrowid, "questions": public, "based_on": len(mistakes)}


@app.post("/api/quiz/{quiz_id}/submit")
def submit_quiz(quiz_id: int, body: QuizAnswersIn, user: dict = Depends(current_user)):
    with connect() as db:
        quiz = row(db.execute("SELECT * FROM quizzes WHERE id=? AND user_id=?", (quiz_id, user["id"])))
        if not quiz:
            raise HTTPException(404, "Тест не найден")
        data = json.loads(quiz["questions"])
        questions = data["questions"]
        results = []
        for i, q in enumerate(questions):
            given = body.answers[i] if i < len(body.answers) else -1
            results.append({"correct": q["correct"], "given": given, "ok": given == q["correct"],
                            "explanation": q["explanation"]})
        score = sum(r["ok"] for r in results)
        db.execute("UPDATE quizzes SET answers=?, score=? WHERE id=?", (dumps(body.answers), score, quiz_id))
        # Ошибки считаются проработанными, если тест пройден на 80% и выше
        if questions and score / len(questions) >= 0.8 and data.get("mistake_ids"):
            ids = data["mistake_ids"]
            db.execute(f"UPDATE mistakes SET resolved=1 WHERE id IN ({','.join('?' * len(ids))})", ids)
        return {"score": score, "total": len(questions), "results": results}


# ---------- вебхук бота ----------

@app.post("/max/webhook")
async def max_webhook(request: Request):
    if request.app.state.api:
        update = await request.json()
        asyncio.create_task(bot.handle_update(request.app.state.api, update))
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "bot": bool(BOT_TOKEN), "ai": llm.enabled(), "dev": DEV_MODE}


# ---------- мини-приложение ----------

app.mount("/static", StaticFiles(directory=WEBAPP_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(WEBAPP_DIR / "index.html")
