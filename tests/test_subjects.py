"""Несколько предметов: промпт под предмет, проверка SymPy только в математике, выбор предмета в боте."""
from types import SimpleNamespace

from sqlalchemy.orm import Session

import ai
import bot
import db
import tutor


def test_system_prompt_names_the_subject():
    prompt = ai.system_prompt("Закон Ома", 9, "oge", "physics")
    assert "физика" in prompt and "СИ" in prompt
    assert "Логарифмы ВСЕГДА" not in prompt


def test_unknown_subject_falls_back_to_math():
    assert "математика" in ai.system_prompt(subject="astrology")


def test_check_line_only_for_math():
    assert "ПРОВЕРКА" in ai.with_check_line(ai.NEXT_TASK_PROMPT, "math")
    assert "ПРОВЕРКА" not in ai.with_check_line(ai.NEXT_TASK_PROMPT, "russian")
    assert "{nice}" not in ai.with_check_line(ai.TOPIC_INTRO_PROMPT, "literature")


def test_sympy_is_not_applied_outside_math():
    space = SimpleNamespace(subject="chemistry", task_check="уравнение: x = 2")
    result = {"verdict": "correct", "student_answer": "5", "same_task": True}
    assert tutor.apply_math_check(space, dict(result))["verdict"] == "correct"


def test_every_subject_has_topics_for_buttons():
    for key in ai.SUBJECTS:
        topics = ai.SUBJECT_TOPICS[key]
        assert len(topics) % 2 == 0 and len(topics) >= 4


def test_new_space_takes_user_subject_and_switch_restores_it(monkeypatch):
    monkeypatch.setattr(bot, "send", lambda *a, **k: None)
    with Session(db.engine) as session:
        user = db.get_user(session, 9101, "Аня")
        bot.handle_button(session, user, 1, "subj:russian")
        assert user.subject == "russian"
        space = db.new_space(session, user, "Причастный оборот")
        session.commit()
        assert space.subject == "russian"
        user.subject = "math"
        tutor.switch_space(session, user, space.id)
        assert user.subject == "russian"


def test_bad_subject_payload_is_ignored(monkeypatch):
    monkeypatch.setattr(bot, "send", lambda *a, **k: None)
    with Session(db.engine) as session:
        user = db.get_user(session, 9102, "Тимур")
        bot.handle_button(session, user, 1, "subj:hack")
        assert user.subject == "math"
