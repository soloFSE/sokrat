"""Забота о ребёнке и удаление данных по 152-ФЗ."""
import pytest
from sqlalchemy.orm import Session

import ai
import db
import tutor


@pytest.mark.parametrize("text", [
    "я не хочу жить", "Меня травят в классе", "хочу умереть", "думаю покончить с собой",
])
def test_distress_gets_support_without_model(monkeypatch, text):
    monkeypatch.setattr(ai, "ask", lambda *a, **k: pytest.fail("в тревожной ситуации модель не вызывается"))
    with Session(db.engine) as session:
        user = db.get_user(session, 501, "Аня")
        result = tutor.reply(session, user, text)
    assert "8-800-2000-122" in result["text"]


@pytest.mark.parametrize("text", ["Как решить x² = 4?", "Мне не нравятся логарифмы", "Жить без формул сложно"])
def test_math_is_not_mistaken_for_distress(text):
    assert not tutor.needs_support(text)


def test_delete_user_data_removes_everything():
    with Session(db.engine) as session:
        user = db.get_user(session, 777, "Тимур")
        space = db.new_space(session, user, "Логарифмы")
        db.add_message(session, space, "user", "привет")
        db.add_check(session, user, space, {"verdict": "error", "error_type": "rule", "step": "ОДЗ"})
        db.create_quiz(session, user, [{"question": "q", "options": ["1", "2"], "correct": 0, "explanation": ""}], [])
        session.commit()

        db.delete_user_data(session, db.get_user(session, 777))
        session.commit()

        assert session.get(db.User, 777) is None
        assert session.query(db.Space).filter_by(user_id=777).count() == 0
        assert session.query(db.Message).filter_by(space_id=space.id).count() == 0
        assert session.query(db.Check).filter_by(user_id=777).count() == 0
        assert session.query(db.Quiz).filter_by(user_id=777).count() == 0
