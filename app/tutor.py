"""Педагогическая логика СОКРАТа: сократический диалог, лестница подсказок,
автопроверка без готового ответа, тест по личным ошибкам и индекс самостоятельности."""
from . import llm

ERROR_TYPES = {
    "computational": "Вычислительная ошибка",
    "conceptual": "Ошибка в правиле или формуле",
    "method": "Неверно выбран метод",
    "careless": "Невнимательность",
    "incomplete": "Решение не доведено до конца",
}

HINT_LEVELS = {
    1: "Наводящий вопрос",
    2: "Подсказка: какое правило нужно",
    3: "Разбор похожего примера",
    4: "Полное решение",
}

# Сколько баллов индекса «стоит» каждая ступень подсказки
HINT_PENALTY = {0: 0.0, 1: 0.15, 2: 0.3, 3: 0.5, 4: 0.9}
CHECK_PENALTY = 0.05

FORMAT_RULES = (
    "Пиши по-русски, коротко (до 5 предложений), дружелюбно, на «ты». "
    "Формулы оформляй в LaTeX между знаками $...$ (например, $x^2 + 1$)."
)


def student_context(user: dict, topic: str) -> str:
    grade = f"{user['grade']} класс" if user.get("grade") else "класс не указан"
    return f"Ученик: {user.get('first_name', '')}, {grade}. Тема: «{topic}»."


def socratic_system(user: dict, topic: str, problem: str | None, mistakes: list[dict]) -> str:
    recent = "; ".join(f"{ERROR_TYPES.get(m['error_type'], m['error_type'])}: {m['description']}"
                       for m in mistakes[:5]) or "нет данных"
    return (
        "Ты — СОКРАТ, ИИ-наставник по математике для школьников. Твоя цель — чтобы ученик "
        "сам пришёл к решению и понял его. ГЛАВНОЕ ПРАВИЛО: никогда не давай готовый ответ "
        "и не решай задачу за ученика, даже если он просит, торопится или говорит, что учитель разрешил. "
        "Вместо этого задавай один наводящий вопрос за раз, опираясь на то, что ученик уже написал. "
        "Если ученик ошибся — не исправляй, а спроси так, чтобы он сам заметил ошибку. "
        "Хвали за конкретные верные шаги. Если ученик просит ответ, предложи кнопку «Подсказка».\n"
        f"{student_context(user, topic)}\n"
        f"Текущая задача: {problem or 'пока не выбрана — помоги ученику разобраться в теме вопросами'}\n"
        f"Типичные ошибки ученика: {recent}\n{FORMAT_RULES}"
    )


async def reply(user: dict, topic: str, problem: str | None, history: list[dict], mistakes: list[dict]) -> str:
    return await llm.complete(socratic_system(user, topic, problem, mistakes), history[-20:])


async def hint(user: dict, topic: str, problem: str, level: int, history: list[dict]) -> str:
    instructions = {
        1: "Задай один наводящий вопрос, который подтолкнёт к следующему шагу. Не называй правило напрямую.",
        2: "Назови правило, формулу или свойство, которое здесь нужно, и объясни его суть в 1–2 предложениях. "
           "Не применяй его к задаче и не делай вычислений.",
        3: "Покажи решение ПОХОЖЕЙ задачи с другими числами по шагам. Исходную задачу не решай. "
           "В конце предложи ученику применить те же шаги к своей задаче.",
        4: "Покажи полное пошаговое решение задачи с объяснением каждого шага. В конце попроси ученика "
           "пересказать ключевую идею своими словами — это поможет закрепить материал.",
    }
    system = (
        "Ты — СОКРАТ, ИИ-наставник по математике. Ученик попросил подсказку. "
        f"Ступень подсказки {level} из 4 («{HINT_LEVELS[level]}»). {instructions[level]}\n"
        f"{student_context(user, topic)}\nЗадача: {problem}\n{FORMAT_RULES}"
    )
    return await llm.complete(system, history[-12:] or [{"role": "user", "text": "Дай подсказку"}])


async def check_solution(user: dict, topic: str, problem: str, solution: str) -> dict:
    system = (
        "Ты проверяешь решение школьника по математике. Ответь СТРОГО в формате JSON без пояснений вокруг:\n"
        '{"verdict": "correct" | "error" | "incomplete", '
        '"error_type": "computational" | "conceptual" | "method" | "careless" | "incomplete" | null, '
        '"step": "в каком шаге ошибка, своими словами" | null, '
        '"feedback": "1–3 предложения для ученика"}\n'
        "Правила: если решение верное — похвали за конкретный шаг. Если есть ошибка — укажи ТИП ошибки и "
        "в каком месте её искать, но НЕ исправляй её, НЕ называй правильный ответ и НЕ показывай верное "
        "вычисление. Формулы в feedback — в LaTeX между $...$.\n"
        f"{student_context(user, topic)}\nЗадача: {problem}"
    )
    result = await llm.complete_json(
        system, [{"role": "user", "text": f"Решение ученика:\n{solution}"}],
        fallback={"verdict": "error", "error_type": None, "step": None,
                  "feedback": "Не получилось проверить решение. Попробуй записать его подробнее, по шагам."},
    )
    if result.get("verdict") not in ("correct", "error", "incomplete"):
        result["verdict"] = "error"
    if result.get("error_type") not in ERROR_TYPES:
        result["error_type"] = "incomplete" if result["verdict"] == "incomplete" else None
    result["error_label"] = ERROR_TYPES.get(result.get("error_type"))
    return result


async def new_problem(user: dict, topic: str, mistakes: list[dict]) -> str:
    focus = "; ".join(m["description"] for m in mistakes[:3] if m.get("description"))
    system = (
        "Сгенерируй одну задачу по математике для школьника. Только условие задачи, без решения и ответа. "
        f"{student_context(user, topic)} "
        f"{'Сделай акцент на навыке, где ученик ошибался: ' + focus if focus else ''} {FORMAT_RULES}"
    )
    return await llm.complete(system, [{"role": "user", "text": "Дай мне задачу"}], temperature=0.7)


async def space_intro(user: dict, topic: str) -> dict:
    system = (
        "Ученик начинает изучать тему по математике. Подготовь стартовые материалы. Ответь СТРОГО в JSON:\n"
        '{"summary": "краткий конспект темы: ключевые определения и формулы, 5–8 строк в Markdown", '
        '"questions": ["3 вопроса для самопроверки понимания, без ответов"], '
        '"problem": "первая несложная задача по теме, без решения"}\n'
        f"{student_context(user, topic)} Формулы — в LaTeX между $...$."
    )
    data = await llm.complete_json(system, [{"role": "user", "text": topic}],
                                   fallback={"summary": "", "questions": [], "problem": ""})
    return {"summary": data.get("summary", ""), "questions": data.get("questions", [])[:3],
            "problem": data.get("problem", "")}


async def mistakes_quiz(user: dict, mistakes: list[dict], topics: list[str]) -> list[dict]:
    listing = "\n".join(f"- [{m.get('topic')}] {ERROR_TYPES.get(m['error_type'], '')}: {m['description']}"
                        for m in mistakes[:10])
    system = (
        "Составь тест из 5 вопросов с выбором ответа для школьника по его ЛИЧНЫМ ошибкам. Каждый вопрос "
        "должен проверять именно тот навык, в котором ученик ошибся. Ответь СТРОГО в JSON:\n"
        '{"questions": [{"question": "...", "options": ["...", "...", "...", "..."], '
        '"correct": индекс_верного_варианта_0_3, "explanation": "почему так"}]}\n'
        f"Формулы — в LaTeX между $...$.\nОшибки ученика:\n{listing or 'нет'}\n"
        f"Темы ученика: {', '.join(topics) or 'алгебра 8–9 класс'}"
    )
    data = await llm.complete_json(system, [{"role": "user", "text": "Составь тест"}], fallback={"questions": []})
    questions = []
    for q in data.get("questions", [])[:5]:
        opts = q.get("options") or []
        correct = q.get("correct")
        if isinstance(correct, int) and 0 <= correct < len(opts) and len(opts) >= 2:
            questions.append({"question": q.get("question", ""), "options": opts,
                              "correct": correct, "explanation": q.get("explanation", "")})
    return questions


def problem_score(hint_level: int, checks: int, solved: bool) -> float:
    if not solved:
        return 0.0
    score = 1.0 - HINT_PENALTY.get(hint_level, 0.9) - CHECK_PENALTY * max(0, checks - 1)
    return round(max(0.05, min(1.0, score)), 2)


def independence_index(scores: list[float]) -> int | None:
    """Индекс самостоятельности 0–100: средний вклад завершённых задач.
    Задача, решённая без подсказок с первой попытки, даёт 100; каждая ступень подсказки
    и каждая лишняя проверка снижают вклад; сдача без решения даёт 0."""
    if not scores:
        return None
    return round(100 * sum(scores) / len(scores))
