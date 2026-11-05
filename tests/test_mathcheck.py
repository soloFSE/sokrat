"""Проверка ответа математикой: эталон через SymPy, ОДЗ, разбор ответа ученика."""
import math

import pytest

import mathcheck as mc


def test_split_check_line_hides_service_line():
    text, spec = mc.split_check_line("🧩 Реши уравнение\nС чего начнёшь?\nПРОВЕРКА: уравнение: x**2 - 5x + 6 = 0")
    assert "ПРОВЕРКА" not in text
    assert spec == "уравнение: x**2 - 5x + 6 = 0"


def test_quadratic_equation():
    assert mc.reference_answer("уравнение: x**2 - 5*x + 6 = 0") == {2, 3}


def test_logarithm_equation_drops_extraneous_root():
    # log₃(x+1) + log₃(x−1) = 2 → x² = 10; корень −√10 не входит в ОДЗ
    roots = mc.reference_answer("уравнение: log(x+1, 3) + log(x-1, 3) = 2")
    assert len(roots) == 1 and abs(next(iter(roots)).real - math.sqrt(10)) < 1e-6


def test_expression_value():
    assert mc.reference_answer("выражение: log(16*4, 2)") == {6}


@pytest.mark.parametrize("answer, expected", [
    ("x = √10", {math.sqrt(10)}),
    ("2 и 3", {2, 3}),
    ("x₁ = -1; x₂ = 4", {-1, 4}),
    ("Ответ: 0,5", None),                 # слово «Ответ» — не число, честно не разбираем
    ("нет корней", set()),
])
def test_parse_student_answer(answer, expected):
    got = mc.parse_answer(answer)
    if expected is None:
        assert got is None
    else:
        assert got is not None and mc.same(got, {complex(v) for v in expected})


def test_verdict():
    spec = "уравнение: x**2 - 5*x + 6 = 0"
    assert mc.verdict(spec, "3 и 2") is True
    assert mc.verdict(spec, "x = 6; x = -1") is False
    assert mc.verdict(spec, "3") is False               # потерян корень
    assert mc.verdict("нет", "3") is None               # задачу нельзя проверить математикой
    assert mc.verdict(spec, "не знаю") is None


def test_no_code_execution_through_answer():
    assert mc.parse_answer("__import__('os').system('echo hi')") is None


# ---------- математика поверх вердикта модели (tutor.apply_math_check) ----------

import tutor


class Space:
    task_check = "уравнение: x**2 - 5*x + 6 = 0"


def model(verdict, answer, same_task=True):
    return {"verdict": verdict, "student_answer": answer, "same_task": same_task, "error_type": None,
            "error_label": None, "step": None, "feedback": "отзыв модели"}


def test_math_overrules_model_that_praised_wrong_answer():
    result = tutor.apply_math_check(Space(), model("correct", "6; -1"))
    assert result["verdict"] == "error" and result["math_checked"]


def test_math_overrules_model_that_rejected_right_answer():
    result = tutor.apply_math_check(Space(), model("error", "2; 3"))
    assert result["verdict"] == "correct"


def test_math_is_skipped_for_another_task():
    result = tutor.apply_math_check(Space(), model("correct", "7", same_task=False))
    assert result["verdict"] == "correct" and "math_checked" not in result


def test_math_is_skipped_when_answer_is_unclear():
    result = tutor.apply_math_check(Space(), model("incomplete", None))
    assert result["verdict"] == "incomplete" and "math_checked" not in result


def test_remember_task_hides_service_line():
    class S:
        task_check = task_text = ""
    shown = tutor.remember_task(S, "📘 О теме\n...\n🧩 Реши x² − 5x + 6 = 0\nС чего начнёшь?\n"
                                   "ПРОВЕРКА: уравнение: x**2 - 5*x + 6 = 0")
    assert "ПРОВЕРКА" not in shown
    assert S.task_check == "уравнение: x**2 - 5*x + 6 = 0"
    assert S.task_text.startswith("🧩 Реши")


# ---------- повторная сдача решённой задачи не накручивает индекс ----------

from sqlalchemy.orm import Session

import ai
import db


def test_solved_task_counts_once(monkeypatch):
    monkeypatch.setattr(tutor, "_requests", tutor.defaultdict(tutor.deque))
    monkeypatch.setattr(ai, "check_solution", lambda *a, **k: {
        "verdict": "correct", "error_type": None, "error_label": None, "step": None,
        "feedback": "Верно", "student_answer": "2; 3", "same_task": True})
    with Session(db.engine) as session:
        user = db.get_user(session, 7001, "Аня")
        space = db.new_space(session, user, "Квадратные уравнения")
        tutor.remember_task(space, "🧩 Реши x² − 5x + 6 = 0\nПРОВЕРКА: уравнение: x**2 - 5*x + 6 = 0")
        session.commit()

        first = tutor.check(session, user, "D = 1, ответ 2 и 3")
        second = tutor.check(session, user, "D = 1, ответ 2 и 3")
        third = tutor.check(session, user, "по-другому записал: x1=2, x2=3")
        assert first["verdict"] == "correct"
        assert second["verdict"] == third["verdict"] == "already"
        assert db.independence(session, user)["solved"] == 1        # индекс посчитан по одной задаче

        # следующая задача снова засчитывается
        tutor.remember_task(space, "🧩 Реши x² − 7x + 12 = 0\nПРОВЕРКА: уравнение: x**2 - 7*x + 12 = 0")
        monkeypatch.setattr(ai, "check_solution", lambda *a, **k: {
            "verdict": "correct", "error_type": None, "error_label": None, "step": None,
            "feedback": "Верно", "student_answer": "3; 4", "same_task": True})
        assert tutor.check(session, user, "ответ 3 и 4")["verdict"] == "correct"
        assert db.independence(session, user)["solved"] == 2


def test_same_own_solution_counts_once(monkeypatch):
    monkeypatch.setattr(tutor, "_requests", tutor.defaultdict(tutor.deque))
    monkeypatch.setattr(ai, "check_solution", lambda *a, **k: {
        "verdict": "correct", "error_type": None, "error_label": None, "step": None, "feedback": "Верно"})
    with Session(db.engine) as session:
        user = db.get_user(session, 7002, "Тимур")
        db.new_space(session, user)                       # свободный разговор, задачу дал сам ученик
        session.commit()
        assert tutor.check(session, user, "15% от 200 = 30")["verdict"] == "correct"
        assert tutor.check(session, user, "15%  от 200 =  30")["verdict"] == "already"
        assert db.independence(session, user)["solved"] == 1
