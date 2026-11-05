"""Проверка ответа математикой, а не нейросетью.

Нейросеть ошибается в арифметике, поэтому верность ответа решает SymPy:
1. к каждой задаче модель дописывает служебную строку «ПРОВЕРКА: …» с уравнением или выражением;
2. SymPy сам решает уравнение (с учётом ОДЗ) или вычисляет выражение — это эталон;
3. ответ ученика сравнивается с эталоном численно.
Модель остаётся только для объяснения, где ошибка. Если строку разобрать не удалось —
возвращаем None, и проверка идёт по-старому, через модель.
"""
import re

import sympy as sp
from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application, parse_expr,
                                        standard_transformations)

x = sp.Symbol("x")
TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
ALLOWED = {"x": x, "sqrt": sp.sqrt, "log": sp.log, "ln": sp.log, "exp": sp.exp, "pi": sp.pi, "E": sp.E,
           "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "tg": sp.tan, "Abs": sp.Abs, "abs": sp.Abs}
TOLERANCE = 1e-6

CHECK_LINE = re.compile(r"^\s*ПРОВЕРКА:\s*(.*)$", re.MULTILINE)


def split_check_line(text: str) -> tuple[str, str]:
    """Отделяет служебную строку от текста задачи: (текст для ученика, строка проверки или '')."""
    match = CHECK_LINE.search(text)
    if not match:
        return text, ""
    return CHECK_LINE.sub("", text).rstrip(), match.group(1).strip()


def _parse(expr: str):
    """Безопасный разбор формулы: только известные функции и переменная x, без произвольного кода."""
    expr = (expr.replace("π", "pi").replace("·", "*").replace("×", "*")
            .replace("−", "-").replace("²", "**2").replace("³", "**3"))
    expr = re.sub(r"(\d),(\d)", r"\1.\2", expr)                # десятичная запятая: 0,5 → 0.5
    expr = re.sub(r"√\s*(\d+(?:\.\d+)?|[a-z])", r"sqrt(\1)", expr)   # √10 → sqrt(10)
    expr = expr.replace("√", "sqrt")                            # √(x+1) → sqrt(x+1)
    if re.search(r"__|import|lambda|\[|\]|;", expr):
        raise ValueError("недопустимая запись")
    return parse_expr(expr, local_dict=ALLOWED, global_dict={"Integer": sp.Integer, "Float": sp.Float,
                                                             "Rational": sp.Rational, "Symbol": sp.Symbol},
                      transformations=TRANSFORMS)


def _defined(expression, value) -> bool:
    """Подставляем корень в исходное выражение: если что-то не определено (лог отрицательного,
    деление на ноль, корень из отрицательного) — корень посторонний, его отбрасываем (это и есть ОДЗ)."""
    result = expression.subs(x, value).evalf()
    return result.is_real is not False and result.is_finite is not False and not result.has(sp.zoo, sp.nan)


def reference_answer(spec: str) -> set | None:
    """Эталонный ответ по строке проверки: множество чисел или None, если проверить нельзя.

    Форматы: «уравнение: <левая часть> = <правая часть>» (переменная x) и «выражение: <выражение>».
    """
    kind, _, body = spec.partition(":")
    kind, body = kind.strip().lower(), body.strip()
    try:
        if kind == "уравнение" and body.count("=") == 1:
            left, right = (_parse(part) for part in body.split("="))
            roots = sp.solveset(sp.Eq(left, right), x, domain=sp.S.Reals)
            if roots is sp.S.EmptySet:
                return set()                     # корней нет — правильный ответ «нет корней»
            if isinstance(roots, sp.FiniteSet):
                candidates = list(roots)
            elif isinstance(roots, sp.ConditionSet):
                # solveset не справился (например, с логарифмами) — пробуем solve и берём действительные корни
                candidates = [r for r in sp.solve(sp.Eq(left, right), x) if r.evalf().is_real]
                if not candidates:
                    return None              # не нашли решений — не судим, чтобы не обидеть ученика
            else:
                return None                      # бесконечно много корней (sin x = 0) — числами не сравнить
            return {complex(r.evalf()) for r in candidates if _defined(left, r) and _defined(right, r)}
        if kind == "выражение":
            value = sp.nsimplify(_parse(body)).evalf()
            if value.free_symbols:
                return None
            return {complex(value)}
    except Exception:
        return None
    return None


def parse_answer(answer: str) -> set | None:
    """Ответ ученика («x = √10», «2 и 3», «x₁ = -1; x₂ = 4», «нет корней») → множество чисел."""
    if answer is None:
        return None
    text = str(answer).lower()
    if re.search(r"нет (корней|решений)|корней нет|решений нет|∅", text):
        return set()
    text = re.sub(r"x\s*[₀-₉0-9]*\s*=", " ", text)          # убираем «x =», «x₁ =»
    parts = re.split(r";|\bи\b|\bили\b|,\s+(?=-?\d)|\n", text)
    values = set()
    for part in parts:
        part = part.strip(" .{}()")
        if not part:
            continue
        try:
            value = _parse(part).evalf()
        except Exception:
            return None
        if value.free_symbols:
            return None
        values.add(complex(value))
    return values or None


def same(a: set, b: set) -> bool:
    """Совпадают ли два ответа с точностью до округления."""
    if len(a) != len(b):
        return False
    return all(any(abs(u - v) < TOLERANCE for v in b) for u in a)


def verdict(spec: str, student_answer: str) -> bool | None:
    """True — ответ верный, False — неверный, None — математикой проверить не получилось."""
    if not spec:
        return None
    expected = reference_answer(spec)
    given = parse_answer(student_answer)
    if expected is None or given is None:
        return None
    return same(expected, given)
