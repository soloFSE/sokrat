"""«Мозг» СОКРАТа: всё, что умеет наставник, в одном месте.

Бот (bot.py) и сайт (web.py) — два разных «лица», но оба вызывают эти функции.
Поэтому поведение везде одинаковое, а прогресс ученика общий. Здесь нет ничего про MAX
или веб: функции получают ученика и текст, а возвращают данные — как их показать, решает интерфейс.
"""
import json

import ai
import db

HISTORY_LIMIT = 20          # сколько последних сообщений отправлять в ИИ
FREE_TOPIC = "Свободный разговор"
MAX_HINTS = 3


class TutorError(Exception):
    """Понятная ученику ошибка: «подсказки кончились», «нет ошибок для теста» и т. п."""


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

def open_topic(session, user, topic: str) -> tuple:
    """Новая тема: конспект по уровню ученика и первая задача. Возвращает (space, текст)."""
    space = db.new_space(session, user, topic.strip()[:200])
    session.commit()
    intro = ai.topic_intro(space.topic, **profile(user))
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

def reply(session, user, text: str, image: bytes | None = None) -> dict:
    """Обычное сообщение ученика в текущей теме: ответ наставника."""
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
    space.hints += 1
    session.commit()
    text = ai.hint(history(session, space), space.hints, topic_of(space), **profile(user))
    text = f"💡 **Подсказка {space.hints}/{MAX_HINTS} · {ai.HINT_TITLES[space.hints]}**\n\n{text}"
    db.add_message(session, space, "assistant", text)
    session.commit()
    return {"space": space, "text": text}


def next_task(session, user) -> dict:
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
