"""Класс учителя: вступление по коду, задания, уведомления и сводка ошибок класса."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import ai
import bot
import db
import tutor
import web


@pytest.fixture
def no_ai(monkeypatch):
    monkeypatch.setattr(ai, "topic_intro", lambda topic, **kw: f"📘 Конспект: {topic}\n🧩 Задача")
    monkeypatch.setattr(tutor, "_requests", tutor.defaultdict(tutor.deque))


@pytest.fixture
def notified(monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "send", lambda chat_id, text, buttons=None, user_id=None: sent.append((user_id, text)))
    return sent


def test_teacher_class_flow(no_ai, notified):
    client = TestClient(web.app)
    with Session(db.engine) as session:
        teacher = db.get_user(session, 9001, "Мария Ивановна")
        anya = db.get_user(session, 9002, "Аня")
        tima = db.get_user(session, 9003, "Тимур")
        session.commit()
    teacher_h = {"Authorization": f"Bearer {web.sign(9001)}"}
    anya_h = {"Authorization": f"Bearer {web.sign(9002)}"}
    tima_h = {"Authorization": f"Bearer {web.sign(9003)}"}

    # учитель создаёт класс, ученики вступают по коду (регистр и пробелы не важны)
    created = client.post("/api/classes", json={"name": "9 Б"}, headers=teacher_h).json()
    assert client.post("/api/classes/join", json={"code": " " + created["code"].lower()}, headers=anya_h).status_code == 200
    assert client.post("/api/classes/join", json={"code": created["code"]}, headers=tima_h).status_code == 200
    assert client.post("/api/classes/join", json={"code": "НЕТТАКОГО"}, headers=anya_h).status_code == 400

    # задание: каждый ученик получает сообщение в MAX с кнопкой
    r = client.post(f"/api/classes/{created['id']}/assignments",
                    json={"topic": "Логарифмы", "note": "реши 3 задачи"}, headers=teacher_h).json()
    assert r["students"] == 2 and r["notified"] == 2
    assert {uid for uid, _ in notified} == {9002, 9003}

    # Аня начинает задание: в чате виден комментарий учителя
    space = client.post(f"/api/assignments/{r['id']}/start", headers=anya_h).json()
    assert "реши 3 задачи" in space["messages"][0]["text"]

    # Аня ошиблась и потом решила; у Тимура ошибка в правиле
    with Session(db.engine) as session:
        anya, tima = db.get_user(session, 9002), db.get_user(session, 9003)
        s = session.get(db.Space, space["id"])
        db.add_check(session, anya, s, {"verdict": "error", "error_type": "rule", "step": "ОДЗ"})
        db.add_check(session, anya, s, {"verdict": "correct"})
        tspace = db.new_space(session, tima, "Логарифмы")
        db.add_check(session, tima, tspace, {"verdict": "error", "error_type": "rule", "step": "свойство"})
        session.commit()

    dash = client.get(f"/api/classes/{created['id']}", headers=teacher_h).json()
    assert dash["code"] == created["code"]
    assert {s["name"] for s in dash["students"]} == {"Аня", "Тимур"}
    assert dash["assignments"][0]["started"] == 1 and dash["assignments"][0]["solved"] == 1
    # у Ани ошибка проработана решением, но в «ошибках в работе» она остаётся до теста — как и у Тимура
    assert dash["common_mistakes"][0]["type"] == ai.ERROR_TYPES["rule"]

    # ученик не может открыть кабинет учителя и выдать задание
    assert client.get(f"/api/classes/{created['id']}", headers=anya_h).status_code == 400
    assert client.post(f"/api/classes/{created['id']}/assignments", json={"topic": "Хаки"},
                       headers=anya_h).status_code == 400

    # ученик видит свой класс и задание с отметкой
    mine = client.get("/api/classes", headers=anya_h).json()["student"]
    assert mine["name"] == "9 Б" and mine["assignments"][0]["solved"] == 1


def test_student_cannot_start_assignment_of_other_class(no_ai):
    with Session(db.engine) as session:
        teacher = db.get_user(session, 9101, "Учитель")
        outsider = db.get_user(session, 9102, "Чужой")
        classroom = tutor.create_classroom(session, teacher, "10 А")
        assignment, _ = tutor.create_assignment(session, teacher, classroom.id, "Проценты")
        with pytest.raises(tutor.TutorError):
            tutor.start_assignment(session, outsider, assignment.id)


def test_deleting_teacher_keeps_students(no_ai):
    with Session(db.engine) as session:
        teacher = db.get_user(session, 9201, "Учитель")
        student = db.get_user(session, 9202, "Ученик")
        classroom = tutor.create_classroom(session, teacher, "8 В")
        tutor.join_classroom(session, student, classroom.code)
        db.delete_user_data(session, teacher)
        session.commit()
        assert session.get(db.User, 9202).classroom_id is None
        assert session.get(db.Classroom, classroom.id) is None
