"""База данных СОКРАТа: SQLite-файл sokrat.db рядом с программой.

Таблицы:
  users    — ученики (id = id пользователя в MAX)
  spaces   — «пространства»: разговор по одной теме (из презентации)
  messages — все сообщения ученика и наставника внутри пространства
  checks   — проверки решений: верно / ошибка и её тип
  quizzes  — тесты по личным ошибкам
"""
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import ForeignKey, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

# База лежит рядом с программой (или там, куда указывает DB_PATH — например, в Docker)
DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent / "sokrat.db"))
# check_same_thread=False: бот и веб-кабинет работают в разных потоках и пользуются одной базой
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)          # user_id из MAX
    name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    # Пространство, в котором ученик сейчас общается
    current_space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id", use_alter=True))
    # Чего бот ждёт от ученика: "chat" — обычный диалог, "topic" — название новой темы
    mode: Mapped[str] = mapped_column(String(20), default="chat")
    # Одноразовый код для входа в веб-кабинет (бот присылает его по кнопке)
    web_code: Mapped[str | None] = mapped_column(String(6))
    web_code_expires: Mapped[datetime | None] = mapped_column()
    # Профиль: от него зависят глубина объяснений и сложность задач
    grade: Mapped[int | None] = mapped_column()                 # класс 5–11
    goal: Mapped[str | None] = mapped_column(String(20))        # school | oge | ege_base | ege_prof

    spaces: Mapped[list["Space"]] = relationship(back_populates="user", foreign_keys="Space.user_id")


class Space(Base):
    __tablename__ = "spaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    topic: Mapped[str] = mapped_column(String(200), default="Свободный разговор")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    hints: Mapped[int] = mapped_column(default=0)               # подсказок по текущей задаче (0–3)

    user: Mapped[User] = relationship(back_populates="spaces", foreign_keys=[user_id])
    messages: Mapped[list["Message"]] = relationship(back_populates="space", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id"))
    role: Mapped[str] = mapped_column(String(20))               # "user" или "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    space: Mapped[Space] = relationship(back_populates="messages")


class Check(Base):
    """Одна проверка решения. Если решение неверное — это ошибка ученика:
    из таких записей потом собирается тест и считается индекс самостоятельности."""
    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id"))
    topic: Mapped[str] = mapped_column(String(200), default="")
    verdict: Mapped[str] = mapped_column(String(20))            # correct | error | incomplete
    error_type: Mapped[str | None] = mapped_column(String(30))  # см. ERROR_TYPES в ai.py
    description: Mapped[str] = mapped_column(Text, default="")  # где именно ошибка
    hints: Mapped[int] = mapped_column(default=0)               # сколько подсказок взял до этой проверки
    resolved: Mapped[bool] = mapped_column(default=False)       # ошибка проработана в тесте
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class Quiz(Base):
    """Тест по личным ошибкам ученика. Вопросы и ответы храним как JSON-текст."""
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    questions: Mapped[str] = mapped_column(Text)                # [{"question", "options", "correct", "explanation"}]
    answers: Mapped[str] = mapped_column(Text, default="[]")    # номера выбранных вариантов
    mistake_ids: Mapped[str] = mapped_column(Text, default="[]")  # по каким ошибкам составлен
    score: Mapped[int | None] = mapped_column()                  # None, пока тест не закончен
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


# Создаём таблицы, если их ещё нет (при первом запуске)
Base.metadata.create_all(engine)

# create_all не добавляет новые столбцы в уже существующие таблицы — добавляем вручную
NEW_COLUMNS = {
    "users": {
        "mode": "VARCHAR(20) DEFAULT 'chat'",
        "web_code": "VARCHAR(6)",
        "web_code_expires": "DATETIME",
        "grade": "INTEGER",
        "goal": "VARCHAR(20)",
    },
    "spaces": {"hints": "INTEGER DEFAULT 0"},
    "checks": {"hints": "INTEGER DEFAULT 0"},
}
with engine.begin() as conn:
    for table, new_columns in NEW_COLUMNS.items():
        columns = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")]
        for name, sql_type in new_columns.items():
            if name not in columns:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


# ---------- функции, которые использует бот ----------

def get_user(session: Session, user_id: int, name: str = "") -> User:
    """Находит ученика или создаёт нового при первом сообщении."""
    user = session.get(User, user_id)
    if user is None:
        user = User(id=user_id, name=name)
        session.add(user)
        session.flush()
    return user


def current_space(session: Session, user: User) -> Space:
    """Текущее пространство ученика; если его нет — создаём."""
    if user.current_space_id:
        return session.get(Space, user.current_space_id)
    return new_space(session, user)


def new_space(session: Session, user: User, topic: str = "Свободный разговор") -> Space:
    space = Space(user_id=user.id, topic=topic)
    session.add(space)
    session.flush()                     # чтобы у space появился id
    user.current_space_id = space.id
    return space


def add_message(session: Session, space: Space, role: str, content: str) -> None:
    session.add(Message(space_id=space.id, role=role, content=content))


def add_check(session: Session, user: User, space: Space, result: dict) -> None:
    session.add(Check(
        user_id=user.id,
        space_id=space.id,
        topic=space.topic,
        verdict=result["verdict"],
        error_type=result.get("error_type"),
        description=result.get("step") or "",
        hints=space.hints,
    ))
    if result["verdict"] == "correct":
        space.hints = 0                 # задача решена — подсказки к следующей считаем заново


def list_spaces(session: Session, user: User, limit: int = 8) -> list[Space]:
    """Последние темы ученика (без пустых «свободных разговоров»)."""
    return session.scalars(
        select(Space)
        .where(Space.user_id == user.id, Space.messages.any())
        .order_by(Space.id.desc())
        .limit(limit)
    ).all()


def get_history(session: Session, space: Space, limit: int) -> list[dict]:
    """Последние limit сообщений пространства в формате для GigaChat."""
    rows = session.scalars(
        select(Message).where(Message.space_id == space.id).order_by(Message.id.desc()).limit(limit)
    ).all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


# ---------- ошибки, тесты и индекс самостоятельности ----------

def open_mistakes(session: Session, user: User, limit: int = 10) -> list[Check]:
    """Ошибки ученика, которые ещё не проработаны в тесте (сначала свежие)."""
    return session.scalars(
        select(Check)
        .where(Check.user_id == user.id, Check.verdict != "correct", Check.resolved.is_(False))
        .order_by(Check.id.desc())
        .limit(limit)
    ).all()


ERROR_PENALTY = 20      # сколько баллов снимает каждая неудачная проверка перед верным решением
HINT_PENALTY = 15       # сколько снимает каждая подсказка
INDEX_WINDOW = 10       # индекс считается по последним 10 решённым задачам


def independence(session: Session, user: User) -> dict:
    """Индекс самостоятельности 0–100 и статистика ученика.

    Идём по проверкам ученика по порядку. В каждом пространстве считаем неудачные проверки,
    пока не придёт верная. Задача, решённая сама с первой проверки, = 100 баллов,
    каждая неудачная попытка перед ней −20, каждая подсказка −15.
    Индекс = среднее по последним 10 решённым задачам.
    """
    checks = session.scalars(select(Check).where(Check.user_id == user.id).order_by(Check.id)).all()
    errors_in_space: dict[int, int] = {}
    scores = []
    history = []        # как менялся индекс после каждой решённой задачи — для графика в веб-кабинете
    for check in checks:
        if check.verdict == "correct":
            errors = errors_in_space.pop(check.space_id, 0)
            scores.append(max(0, 100 - ERROR_PENALTY * errors - HINT_PENALTY * (check.hints or 0)))
            window = scores[-INDEX_WINDOW:]
            history.append({"date": check.created_at.strftime("%d.%m"), "score": scores[-1],
                            "index": round(sum(window) / len(window)), "topic": check.topic})
        else:
            errors_in_space[check.space_id] = errors_in_space.get(check.space_id, 0) + 1

    recent = scores[-INDEX_WINDOW:]
    mistake_types: dict[str, int] = {}
    for mistake in open_mistakes(session, user, limit=100):
        mistake_types[mistake.error_type] = mistake_types.get(mistake.error_type, 0) + 1
    return {
        "index": round(sum(recent) / len(recent)) if recent else None,
        "solved": len(scores),
        "first_try": scores.count(100),
        "mistake_types": mistake_types,          # {"computational": 2, ...}
        "history": history[-30:],
    }


def create_quiz(session: Session, user: User, questions: list, mistakes: list[Check]) -> Quiz:
    quiz = Quiz(user_id=user.id, questions=json.dumps(questions, ensure_ascii=False),
                mistake_ids=json.dumps([m.id for m in mistakes]))
    session.add(quiz)
    session.flush()
    return quiz


def finish_quiz(session: Session, quiz: Quiz) -> None:
    """Считает результат. Если 80% и выше — ошибки, по которым был тест, считаются проработанными."""
    questions = json.loads(quiz.questions)
    answers = json.loads(quiz.answers)
    quiz.score = sum(1 for q, a in zip(questions, answers) if q["correct"] == a)
    if quiz.score >= 0.8 * len(questions):
        for mistake_id in json.loads(quiz.mistake_ids):
            mistake = session.get(Check, mistake_id)
            if mistake:
                mistake.resolved = True


# ---------- веб-кабинет ----------

CODE_LIFETIME = timedelta(minutes=10)


def new_login_code(session: Session, user: User) -> str:
    """Одноразовый 6-значный код для входа в веб-кабинет, действует 10 минут."""
    user.web_code = f"{secrets.randbelow(10**6):06d}"
    user.web_code_expires = datetime.now() + CODE_LIFETIME
    return user.web_code


def user_by_code(session: Session, code: str) -> User | None:
    """Находит ученика по коду и сразу «сжигает» код, чтобы им нельзя было войти второй раз."""
    user = session.scalars(select(User).where(User.web_code == code)).first()
    if user is None or user.web_code_expires is None or user.web_code_expires < datetime.now():
        return None
    user.web_code = None
    user.web_code_expires = None
    return user


def quiz_history(session: Session, user: User, limit: int = 10) -> list[Quiz]:
    return session.scalars(
        select(Quiz).where(Quiz.user_id == user.id, Quiz.score.is_not(None))
        .order_by(Quiz.id.desc()).limit(limit)
    ).all()


def space_stats(session: Session, space: Space) -> dict:
    """Сколько задач решено в теме и сколько было ошибок."""
    checks = session.scalars(select(Check).where(Check.space_id == space.id)).all()
    return {
        "solved": sum(c.verdict == "correct" for c in checks),
        "mistakes": sum(c.verdict != "correct" for c in checks),
    }
