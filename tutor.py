"""«Мозг» СОКРАТа: всё, что умеет наставник, в одном месте.

Бот (bot.py) и сайт (web.py) — два разных «лица», но оба вызывают эти функции.
Поэтому поведение везде одинаковое, а прогресс ученика общий. Здесь нет ничего про MAX
или веб: функции получают ученика и текст, а возвращают данные — как их показать, решает интерфейс.
"""
import json
import re
import threading
import time
from collections import defaultdict, deque

import ai
import db

HISTORY_LIMIT = 20          # сколько последних сообщений отправлять в ИИ
FREE_TOPIC = "Свободный разговор"
MAX_HINTS = 3

# Ограничение запросов к ИИ на одного ученика: живому ученику хватит с запасом,
# а скрипт или «залипшая» кнопка не съест весь лимит GigaChat
LIMITS = [(60, 12), (24 * 3600, 300)]       # не больше 12 в минуту и 300 в сутки


class TutorError(Exception):
    """Понятная ученику ошибка: «подсказки кончились», «нет ошибок для теста» и т. п."""


_requests: dict[int, deque] = defaultdict(deque)
_requests_lock = threading.Lock()


# Тревожные сигналы: на них отвечаем заготовленным текстом сразу, не полагаясь на модель
DISTRESS = re.compile(
    r"не хочу жить|жить не хочу|покончить с собой|убить себя|суицид|самоубий|порезать себя|"
    r"причинить себе|хочу умереть|меня (бьют|травят|избивают|унижают)|(травят|издеваются|бьют) меня|"
    r"травля|меня трогают|мне страшно дома|никому не нужен",
    re.IGNORECASE,
)
SUPPORT_TEXT = (
    "Мне очень жаль, что тебе сейчас так тяжело. Ты не должен справляться с этим один 💙\n\n"
    "Пожалуйста, расскажи об этом взрослому, которому доверяешь: родителям, учителю или школьному психологу.\n\n"
    "Если хочется поговорить прямо сейчас — позвони на **Детский телефон доверия: 8-800-2000-122**. "
    "Это бесплатно, анонимно и круглосуточно, там помогут.\n\n"
    "Я рядом, и к математике мы вернёмся, когда ты будешь готов."
)


def needs_support(text: str) -> bool:
    return bool(DISTRESS.search(text or ""))


def spend_request(user_id: int) -> None:
    """Учитывает один запрос к ИИ. Если ученик превысил лимит — TutorError с понятным текстом."""
    now = time.time()
    with _requests_lock:
        times = _requests[user_id]
        while times and now - times[0] > LIMITS[-1][0]:
            times.popleft()                      # забываем запросы старше суток
        for window, limit in LIMITS:
            if sum(1 for t in times if now - t <= window) >= limit:
                if window == 60:
                    raise TutorError("Ты пишешь очень быстро 🙂 Подожди минутку и продолжим.")
                raise TutorError("На сегодня лимит вопросов исчерпан — отдохни, завтра продолжим 💪")
        times.append(now)


def profile(user) -> dict:
    return {"grade": user.grade, "goal": user.goal}


def topic_of(space) -> str:
    return "" if space.topic == FREE_TOPIC else space.topic


def history(session, space) -> list[dict]:
    return db.get_history(session, space, HISTORY_LIMIT)


def photo_to_text(image: bytes | None, text: str) -> tuple[str, str]:
    """Сообщение ученика → текст для ИИ. Фото распознаём.
    Возвращает (текст для истории, распознанный текст с фото или '')."""
    if not image:
        return text, ""
    recognized = ai.read_image(image)
    content = f"[Ученик прислал фото. На нём:]\n{recognized}"
    if text:
        content += f"\n\n[Подпись ученика к фото:] {text}"
    return content, recognized


# ---------- темы ----------

def open_topic(session, user, topic: str, assignment=None) -> tuple:
    """Новая тема: конспект по уровню ученика и первая задача. Возвращает (space, текст).
    Если тему выдал учитель (assignment), тема привязывается к заданию, а комментарий учителя виден в чате."""
    spend_request(user.id)
    space = db.new_space(session, user, topic.strip()[:200])
    if assignment is not None:
        space.assignment_id = assignment.id
    session.commit()
    intro = ai.topic_intro(space.topic, **profile(user))
    if assignment is not None and assignment.note:
        intro = f"📌 **Задание от учителя:** {assignment.note}\n\n{intro}"
    db.add_message(session, space, "assistant", intro)
    session.commit()
    return space, intro


def switch_space(session, user, space_id: int):
    space = session.get(db.Space, space_id)
    if space is None or space.user_id != user.id:      # чужую тему открыть нельзя
        raise TutorError("Тема не найдена")
    user.current_space_id = space.id
    session.commit()
    return space


# ---------- диалог, подсказки, задачи ----------

def support(session, user, text: str) -> dict:
    """Ученику плохо: отвечаем заботой и телефоном доверия, без модели и без лимитов."""
    space = db.current_space(session, user)
    db.add_message(session, space, "user", text)
    db.add_message(session, space, "assistant", SUPPORT_TEXT)
    session.commit()
    return {"space": space, "text": SUPPORT_TEXT, "recognized": "", "verdict": None}


def reply(session, user, text: str, image: bytes | None = None) -> dict:
    """Обычное сообщение ученика в текущей теме: ответ наставника."""
    if needs_support(text):
        return support(session, user, text)
    spend_request(user.id)
    space = db.current_space(session, user)
    content, recognized = photo_to_text(image, text)
    db.add_message(session, space, "user", content)
    session.commit()
    answer = ai.ask(history(session, space), topic_of(space), **profile(user))
    db.add_message(session, space, "assistant", answer)
    session.commit()
    return {"space": space, "text": answer, "recognized": recognized}


def hint(session, user) -> dict:
    """Следующая ступень подсказки: намёк → правило → разбор похожей задачи."""
    space = db.current_space(session, user)
    if space.hints >= MAX_HINTS:
        raise TutorError("Подсказок к этой задаче больше нет. Попробуй сам и отправь решение на проверку — "
                         "я покажу, где ошибка. Или возьми другую задачу.")
    spend_request(user.id)
    space.hints += 1
    session.commit()
    text = ai.hint(history(session, space), space.hints, topic_of(space), **profile(user))
    text = f"💡 **Подсказка {space.hints}/{MAX_HINTS} · {ai.HINT_TITLES[space.hints]}**\n\n{text}"
    db.add_message(session, space, "assistant", text)
    session.commit()
    return {"space": space, "text": text}


def next_task(session, user) -> dict:
    spend_request(user.id)
    space = db.current_space(session, user)
    space.hints = 0                     # новая задача — подсказки заново
    session.commit()
    task = ai.next_task(history(session, space), topic_of(space), **profile(user))
    db.add_message(session, space, "assistant", task)
    session.commit()
    return {"space": space, "text": task}


# ---------- автопроверка ----------

def check(session, user, text: str, image: bytes | None = None) -> dict:
    """Проверяет решение: верно / тип ошибки и где искать. Ошибки сохраняются для теста и индекса."""
    if needs_support(text):
        return support(session, user, text)
    spend_request(user.id)
    space = db.current_space(session, user)
    content, recognized = photo_to_text(image, text)
    result = ai.check_solution(history(session, space), content, topic_of(space))
    hints_used = space.hints

    if result["verdict"] == "correct":
        text = f"✅ **Верно!** {result['feedback']}"
        if hints_used:
            text += f"\n\nПодсказок взято: {hints_used}. В следующий раз попробуй сначала сам — индекс вырастет 💪"
    elif result["verdict"] == "unknown":
        text = f"🤔 {result['feedback']}"
    else:
        text = f"⚠️ **{result['error_label']}.** {result['feedback']}"
        if result["step"]:
            text += f"\n\n🔎 **Где искать:** {result['step']}"
        text += "\n\nПопробуй найти и исправить сам, а потом пришли решение ещё раз."

    if result["verdict"] != "unknown":
        db.add_check(session, user, space, result)
    # Проверка тоже часть диалога: наставник должен помнить, что решение уже смотрели
    db.add_message(session, space, "user", f"[Решение на проверку:]\n{content}")
    db.add_message(session, space, "assistant", text)
    session.commit()
    return {"space": space, "text": text, "verdict": result["verdict"], "recognized": recognized}


# ---------- тест по ошибкам ----------

def create_quiz(session, user):
    mistakes = db.open_mistakes(session, user)
    if not mistakes:
        raise TutorError("У тебя нет непроработанных ошибок 👏 Реши задачу и отправь её на проверку — "
                         "если где-то ошибёшься, я соберу тест именно на это место.")
    spend_request(user.id)
    descriptions = [f"[{m.topic}] {ai.ERROR_TYPES.get(m.error_type, 'Ошибка')}: {m.description}" for m in mistakes]
    questions = ai.make_quiz(descriptions)
    if not questions:
        raise TutorError("Не получилось составить тест 😔 Попробуй ещё раз через минуту.")
    quiz = db.create_quiz(session, user, questions, mistakes)
    session.commit()
    return quiz


def public_questions(quiz) -> list[dict]:
    """Вопросы без правильных ответов — их можно показывать ученику."""
    return [{"question": q["question"], "options": q["options"]} for q in json.loads(quiz.questions)]


def answer_quiz(session, user, quiz_id: int, index: int, option: int) -> dict | None:
    """Ответ на вопрос теста. None — если нажали старую кнопку или тест чужой/закончен."""
    quiz = session.get(db.Quiz, quiz_id)
    if quiz is None or quiz.user_id != user.id or quiz.score is not None:
        return None
    answers = json.loads(quiz.answers)
    if index != len(answers):
        return None
    questions = json.loads(quiz.questions)
    answers.append(option)
    quiz.answers = json.dumps(answers)
    q = questions[index]
    result = {"quiz": quiz, "correct": q["correct"], "ok": option == q["correct"],
              "explanation": q["explanation"], "finished": index + 1 == len(questions), "total": len(questions)}
    if result["finished"]:
        db.finish_quiz(session, quiz)
        result["score"] = quiz.score
        result["passed"] = quiz.score >= 0.8 * len(questions)
    session.commit()
    return result


# ---------- класс и задания учителя ----------

def create_classroom(session, teacher, name: str):
    classroom = db.create_classroom(session, teacher, name)
    session.commit()
    return classroom


def join_classroom(session, student, code: str):
    classroom = db.classroom_by_code(session, code)
    if classroom is None:
        raise TutorError("Класс с таким кодом не найден. Проверь код у учителя — он из 6 символов, например K7M2QX.")
    student.classroom_id = classroom.id
    session.commit()
    return classroom


def leave_classroom(session, student) -> None:
    student.classroom_id = None
    session.commit()


def own_classroom(session, teacher, classroom_id: int):
    """Класс, если его ведёт этот учитель; чужой класс посмотреть нельзя."""
    classroom = session.get(db.Classroom, classroom_id)
    if classroom is None or classroom.teacher_id != teacher.id:
        raise TutorError("Класс не найден")
    return classroom


def create_assignment(session, teacher, classroom_id: int, topic: str, note: str = "") -> tuple:
    """Учитель выдаёт тему классу. Возвращает (задание, ученики) — ученикам бот пришлёт уведомление."""
    classroom = own_classroom(session, teacher, classroom_id)
    topic = topic.strip()[:200]
    if len(topic) < 2:
        raise TutorError("Укажи тему задания")
    assignment = db.Assignment(classroom_id=classroom.id, topic=topic, note=note.strip()[:1000])
    session.add(assignment)
    session.commit()
    return assignment, db.class_students(session, classroom)


def start_assignment(session, student, assignment_id: int) -> tuple:
    """Ученик начинает задание: открываем его тему (или продолжаем, если уже начинал)."""
    assignment = session.get(db.Assignment, assignment_id)
    if assignment is None or assignment.classroom_id != student.classroom_id:
        raise TutorError("Задание не найдено — возможно, ты не в этом классе")
    existing = db.assignment_space(session, assignment, student)
    if existing is not None:
        student.current_space_id = existing.id
        session.commit()
        last = next((m.content for m in reversed(existing.messages) if m.role == "assistant"), "")
        return existing, last
    return open_topic(session, student, assignment.topic, assignment)


def teacher_dashboard(session, teacher, classroom_id: int) -> dict:
    """Всё, что видит учитель: ученики с индексом, типичные ошибки класса и выполнение заданий."""
    classroom = own_classroom(session, teacher, classroom_id)
    summary = db.class_summary(session, classroom)
    students = db.class_students(session, classroom)
    total = len(students)
    common_mistakes = [
        {"type": ai.ERROR_TYPES.get(t, t), "students": n, "share": round(100 * n / total) if total else 0}
        for t, n in sorted(summary["type_students"].items(), key=lambda x: -x[1])
    ]
    weak_topics = [{"topic": t, "errors": n} for t, n in sorted(summary["topic_errors"].items(), key=lambda x: -x[1])]
    assignments = []
    for a in db.class_assignments(session, classroom):
        progress = [db.assignment_progress(session, a, s) for s in students]
        assignments.append({
            "id": a.id, "topic": a.topic, "note": a.note, "created": a.created_at.strftime("%d.%m"),
            "started": sum(p["started"] for p in progress),
            "solved": sum(p["solved"] > 0 for p in progress),
            "total": total,
        })
    indexes = [s["index"] for s in summary["students"] if s["index"] is not None]
    return {
        "id": classroom.id, "name": classroom.name, "code": classroom.code,
        "students": summary["students"],
        "class_index": round(sum(indexes) / len(indexes)) if indexes else None,
        "common_mistakes": common_mistakes[:5],
        "weak_topics": weak_topics[:5],
        "assignments": assignments,
    }


def student_classroom(session, student) -> dict | None:
    """Что видит ученик: свой класс и задания с отметкой, начато ли и сколько решено."""
    if not student.classroom_id:
        return None
    classroom = session.get(db.Classroom, student.classroom_id)
    if classroom is None:
        return None
    teacher = session.get(db.User, classroom.teacher_id)
    return {
        "name": classroom.name,
        "teacher": teacher.name if teacher else "",
        "assignments": [{"id": a.id, "topic": a.topic, "note": a.note, "created": a.created_at.strftime("%d.%m"),
                         **db.assignment_progress(session, a, student)}
                        for a in db.class_assignments(session, classroom)],
    }
