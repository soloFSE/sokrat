"""Хранилище SQLite: ученики, пространства, сообщения, задачи и ошибки."""
import json
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,           -- user_id в MAX
    first_name TEXT,
    last_name TEXT,
    grade INTEGER,                    -- класс
    level TEXT DEFAULT 'base',        -- base | advanced
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS spaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    summary TEXT,                     -- конспект темы с ключевыми вопросами
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS problems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    space_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    hint_level INTEGER DEFAULT 0,     -- максимальная ступень подсказки (0..4)
    checks INTEGER DEFAULT 0,         -- сколько раз ученик отправлял решение
    status TEXT DEFAULT 'active',     -- active | solved | given_up
    score REAL,                       -- вклад в индекс самостоятельности (0..1)
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    solved_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    space_id INTEGER NOT NULL,
    problem_id INTEGER,
    role TEXT NOT NULL,               -- user | assistant
    kind TEXT DEFAULT 'chat',         -- chat | hint | check | problem
    text TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    space_id INTEGER,
    problem_id INTEGER,
    topic TEXT,
    error_type TEXT,                  -- computational | conceptual | careless | incomplete
    description TEXT,
    resolved INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    questions TEXT NOT NULL,          -- JSON
    answers TEXT,                     -- JSON
    score INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


def row(cursor) -> dict | None:
    r = cursor.fetchone()
    return dict(r) if r else None


def upsert_user(user: dict) -> dict:
    with connect() as db:
        db.execute(
            "INSERT INTO users (id, first_name, last_name) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET first_name=excluded.first_name, last_name=excluded.last_name",
            (user["id"], user.get("first_name", ""), user.get("last_name", "")),
        )
        return row(db.execute("SELECT * FROM users WHERE id=?", (user["id"],)))


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
