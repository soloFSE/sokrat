import html
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from dotenv import load_dotenv
from sqlalchemy.orm import Session

import db
import tutor
from ai import ERROR_TYPES, GOALS
from db import engine

load_dotenv()
CERT = "russian_trusted_ca.pem"
API = "https://platform-api2.max.ru"
HEADERS = {"Authorization": os.getenv("BOT_TOKEN")}

WEB_URL = os.getenv("WEB_URL", "http://localhost:8000")   # адрес веб-кабинета
MAX_MESSAGE = 3500  # MAX не принимает слишком длинные сообщения — длинные ответы режем на части

# Готовые темы для кнопок; свою тему ученик может написать сообщением
TOPICS = ["Квадратные уравнения", "Линейные функции", "Проценты", "Теорема Пифагора",
          "Системы уравнений", "Степени и корни", "Логарифмы", "Тригонометрия"]
GRADES = [5, 6, 7, 8, 9, 10, 11]
LETTERS = "АБВГ"

HELP = (
    "**Как со мной заниматься**\n\n"
    "📚 **Новая тема** — объясню тему по твоему уровню и дам первую задачу.\n"
    "💬 Можно просто написать вопрос или прислать **фото задачи**.\n"
    "💡 **Подсказка** — если застрял: сначала намёк, потом правило, потом разбор похожей задачи.\n"
    "✔ **Проверить решение** — пришли решение текстом или фото: скажу, верно ли, а если нет — где ошибка.\n"
    "📝 **Тест по ошибкам** — вопросы именно на те места, где ты ошибался.\n"
    "📊 **Мой прогресс** — индекс самостоятельности: насколько ты решаешь сам.\n\n"
    "Я не решаю задачи за тебя — я помогаю дойти до ответа самому. Так ты действительно научишься.\n\n"
    "Команды: /menu — меню, /help — эта справка, /privacy — какие данные я храню, "
    "/delete — удалить все мои данные."
)

PRIVACY = (
    "**Какие данные я храню**\n\n"
    "• имя из профиля MAX, класс и цель (школа, ОГЭ, ЕГЭ);\n"
    "• переписку со мной по темам — чтобы помнить, на чём мы остановились;\n"
    "• результаты проверок решений, ошибки и тесты — для индекса самостоятельности.\n\n"
    "Телефон, фамилию, школу и геолокацию я **не** собираю. Фото задачи используется только для распознавания: "
    "после него сразу удаляется из GigaChat, в базе остаётся лишь распознанный текст.\n\n"
    "Данные хранятся на сервере проекта и никому не передаются. Тексты сообщений обрабатывает "
    "нейросеть GigaChat (Сбер, серверы в России).\n\n"
    "Удалить все свои данные можно в любой момент командой /delete."
)


# ---------- кнопки ----------

def button(text, payload):
    """Кнопка под сообщением. При нажатии бот получит payload."""
    return {"type": "callback", "text": text, "payload": payload}


MENU = [
    [button("📚 Новая тема", "new_topic"), button("📂 Мои темы", "my_topics")],
    [button("📝 Тест по ошибкам", "quiz"), button("📊 Мой прогресс", "progress")],
    [button("🏫 Мой класс", "class"), button("🎓 Мой уровень", "level")],
    [button("❓ Помощь", "help")],
]
MENU_BUTTON = button("☰ Меню", "menu")


def task_keyboard(space):
    """Кнопки под задачей: то, что нужно ученику прямо сейчас, а не всё меню."""
    if space.hints < 3:
        hint_button = button(f"💡 Подсказка {space.hints + 1}/3", "hint")
    else:
        hint_button = button("💡 Подсказки кончились", "hint")
    return [
        [hint_button, button("✔ Проверить решение", "check")],
        [button("➡️ Другая задача", "next"), MENU_BUTTON],
    ]


AFTER_CORRECT = [[button("➡️ Следующая задача", "next"), MENU_BUTTON]]


# ---------- работа с MAX ----------

def to_html(text):
    """Ответ ИИ (**жирный**, ## заголовки) → HTML для MAX. Остальное экранируем,
    чтобы символы < и > в формулах (x < 5) не ломали разметку."""
    text = html.escape(text, quote=False)
    text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)
    return text


def plain(text):
    """Запасной вариант без разметки — если MAX не принял HTML."""
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return text.replace("**", "")


def split_long(text, limit=MAX_MESSAGE):
    """Режет длинный текст на части по абзацам, чтобы каждая влезла в одно сообщение."""
    parts, current = [], ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) + 2 > limit:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{paragraph}" if current else paragraph
        while len(current) > limit:                 # один огромный абзац — режем по длине
            parts.append(current[:limit])
            current = current[limit:]
    if current:
        parts.append(current)
    return parts or [""]


def send(chat_id, text, buttons=None, user_id=None):
    """Отправляет сообщение в чат (chat_id) или лично ученику по его id в MAX (user_id)."""
    target = {"user_id": user_id} if user_id else {"chat_id": chat_id}
    parts = split_long(text)
    for i, part in enumerate(parts):
        body = {"text": to_html(part), "format": "html"}
        if buttons and i == len(parts) - 1:          # кнопки — только под последней частью
            body["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
        resp = httpx.post(f"{API}/messages", headers=HEADERS, params=target,
                          json=body, verify=CERT, timeout=30)
        if resp.status_code >= 400:
            print("MAX не принял сообщение с разметкой:", resp.status_code, resp.text[:200])
            body.update(text=plain(part))
            body.pop("format")
            httpx.post(f"{API}/messages", headers=HEADERS, params=target,
                       json=body, verify=CERT, timeout=30)


def notify_assignment(assignment, teacher_name, students):
    """Рассылает ученикам класса новое задание. Вызывается и из бота, и с сайта учителя.
    Если кому-то не доставилось (например, ученик удалил чат с ботом) — продолжаем с остальными."""
    text = f"📌 **Новое задание{' от ' + teacher_name if teacher_name else ''}:** {assignment.topic}"
    if assignment.note:
        text += f"\n\n{assignment.note}"
    delivered = 0
    for student in students:
        try:
            send(None, text, [[button("▶️ Начать задание", f"assign:{assignment.id}")]], user_id=student.id)
            delivered += 1
        except Exception as e:
            print("Не удалось отправить задание ученику", student.id, repr(e))
    return delivered


def typing(chat_id):
    """Показывает ученику «печатает…», пока ИИ думает."""
    try:
        httpx.post(f"{API}/chats/{chat_id}/actions", headers=HEADERS, json={"action": "typing_on"},
                   verify=CERT, timeout=10)
    except Exception:
        pass


def answer_callback(callback_id):
    """Сообщаем MAX, что нажатие кнопки обработано, — иначе у ученика крутится загрузка."""
    try:
        httpx.post(f"{API}/answers", headers=HEADERS, params={"callback_id": callback_id},
                   json={"notification": "✓"}, verify=CERT, timeout=10)
    except Exception:
        pass


def download(url):
    """Скачивает картинку по ссылке из MAX и возвращает её байты."""
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
    except httpx.ConnectError:
        # Серверы MAX могут использовать сертификат Минцифры
        resp = httpx.get(url, timeout=30, follow_redirects=True, verify=CERT)
    resp.raise_for_status()
    return resp.content


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".gif")


def find_image_url(message):
    """Ссылка на первую картинку в сообщении или None.

    Картинка может прийти двумя способами: как фото (type="image")
    или как файл с картинкой (type="file", имя вроде task.jpg).
    """
    for attachment in message['body'].get('attachments') or []:
        kind = attachment.get('type')
        payload = attachment.get('payload') or {}
        filename = (attachment.get('filename') or payload.get('filename') or '').lower()
        if kind == 'image' or (kind == 'file' and filename.endswith(IMAGE_EXTENSIONS)):
            return payload.get('url')
        print("Вложение не распознано как картинка:", kind, filename)
    return None


# ---------- знакомство: класс и цель ----------

def ask_grade(session, user, chat_id, greeting=False):
    user.mode = "chat"
    session.commit()
    text = ("Привет! Я **СОКРАТ** — наставник по математике 👋\n\n"
            "Я объясняю темы как репетитор, а задачи помогаю решить **самому** — наводящими вопросами "
            "и подсказками. Так ты действительно научишься, а не просто получишь ответ.\n\n"
            if greeting else "")
    text += "В каком ты классе? От этого зависит, как подробно объяснять и какие задачи давать."
    rows = [[button(str(g), f"grade:{g}") for g in GRADES[:4]], [button(str(g), f"grade:{g}") for g in GRADES[4:]]]
    send(chat_id, text, rows)


def ask_goal(session, user, chat_id):
    rows = [[button("📗 Школьная программа", "goal:school")], [button("📘 Готовлюсь к ОГЭ", "goal:oge")],
            [button("📙 ЕГЭ база", "goal:ege_base"), button("📕 ЕГЭ профиль", "goal:ege_prof")]]
    send(chat_id, "Какая у тебя цель?", rows)


def profile_done(session, user, chat_id):
    send(chat_id, f"Отлично, запомнил: {user.grade} класс, {GOALS[user.goal]} ✅\n\n"
                  "С чего начнём? Открой тему — или просто напиши вопрос либо пришли фото задачи 🙂", MENU)


# ---------- темы (пространства) ----------

def ask_for_topic(session, user, chat_id):
    user.mode = "topic"            # следующее сообщение ученика — название темы
    session.commit()
    rows = [[button(TOPICS[i], f"topic:{i}"), button(TOPICS[i + 1], f"topic:{i + 1}")]
            for i in range(0, len(TOPICS), 2)]
    send(chat_id, "Какую тему разберём? Выбери кнопкой или **напиши свою** одним сообщением "
                  "(например, «Показательные неравенства»).", rows + [[MENU_BUTTON]])


def start_topic(session, user, chat_id, topic):
    user.mode = "chat"
    send(chat_id, f"⏳ Готовлю разбор темы «{topic.strip()[:200]}»…")
    typing(chat_id)
    space, intro = tutor.open_topic(session, user, topic)
    send(chat_id, intro, task_keyboard(space))


def show_my_topics(session, user, chat_id):
    spaces = [s for s in db.list_spaces(session, user) if s.topic != tutor.FREE_TOPIC]
    if not spaces:
        send(chat_id, "У тебя пока нет тем. Давай начнём первую!", [[button("📚 Новая тема", "new_topic")]])
        return
    rows = []
    for s in spaces:
        stats = db.space_stats(session, s)
        rows.append([button(f"{s.topic[:40]} · ✅ {stats['solved']}", f"space:{s.id}")])
    send(chat_id, "📂 **Твои темы** (рядом — сколько задач решено). Выбери, чтобы продолжить:",
         rows + [[MENU_BUTTON]])


def open_space(session, user, chat_id, space_id):
    space = tutor.switch_space(session, user, space_id)
    last = next((m.content for m in reversed(space.messages) if m.role == "assistant"), "")
    text = f"Продолжаем тему «**{space.topic}**» 👌"
    if last:
        text += f"\n\nНа чём остановились:\n\n{last}"
    send(chat_id, text, task_keyboard(space))


# ---------- диалог ----------

def photo(chat_id, image_url):
    """Скачивает фото из MAX (если есть) и предупреждает ученика, что его смотрим."""
    if not image_url:
        return None
    send(chat_id, "📷 Смотрю на фото…")
    typing(chat_id)
    return download(image_url)


def with_photo(result):
    """Показываем ученику, что распознали на фото: если ИИ ошибся — он сразу заметит."""
    if result.get("recognized"):
        return f"**Вот что я вижу на фото:**\n{result['recognized']}\n\n{result['text']}"
    return result["text"]


def reply_in_space(session, user, chat_id, text, image_url):
    image = photo(chat_id, image_url)
    typing(chat_id)
    result = tutor.reply(session, user, text, image)
    send(chat_id, with_photo(result), task_keyboard(result["space"]))


def give_hint(session, user, chat_id):
    typing(chat_id)
    result = tutor.hint(session, user)
    send(chat_id, result["text"], task_keyboard(result["space"]))


def give_next_task(session, user, chat_id):
    typing(chat_id)
    result = tutor.next_task(session, user)
    send(chat_id, result["text"], task_keyboard(result["space"]))


# ---------- автопроверка ----------

def ask_for_solution(session, user, chat_id):
    user.mode = "check"            # следующее сообщение ученика — решение на проверку
    session.commit()
    send(chat_id, "✍️ Пришли своё решение **одним сообщением**: шаги и ответ. Можно текстом или фото тетради.\n"
                  "Я скажу, верно ли, а если нет — где искать ошибку.", [[button("↩️ Отмена", "cancel")]])


def check_in_space(session, user, chat_id, text, image_url):
    user.mode = "chat"
    session.commit()
    image = photo(chat_id, image_url)
    send(chat_id, "🔎 Проверяю решение…")
    typing(chat_id)
    result = tutor.check(session, user, text, image)
    keyboard = AFTER_CORRECT if result["verdict"] == "correct" else task_keyboard(result["space"])
    send(chat_id, with_photo(result), keyboard)


# ---------- тест по ошибкам и прогресс ----------

def start_quiz(session, user, chat_id):
    if not db.open_mistakes(session, user):
        send(chat_id, "У тебя нет непроработанных ошибок 👏 Реши задачу и отправь её на проверку — "
                      "если где-то ошибёшься, я соберу тест именно на это место.", MENU)
        return
    send(chat_id, "⏳ Собираю тест по твоим ошибкам. Это займёт около 20 секунд…")
    typing(chat_id)
    quiz = tutor.create_quiz(session, user)
    send_question(chat_id, quiz, 0)


def send_question(chat_id, quiz, index):
    questions = tutor.public_questions(quiz)
    q = questions[index]
    options = "\n".join(f"**{LETTERS[j]})** {o}" for j, o in enumerate(q["options"]))
    buttons = [[button(LETTERS[j], f"qa:{quiz.id}:{index}:{j}") for j in range(len(q["options"]))]]
    send(chat_id, f"📝 **Вопрос {index + 1} из {len(questions)}**\n\n{q['question']}\n\n{options}", buttons)


def answer_question(session, user, chat_id, quiz_id, index, option):
    result = tutor.answer_quiz(session, user, quiz_id, index, option)
    if result is None:
        return                          # старая кнопка или чужой тест
    if result["ok"]:
        send(chat_id, f"✅ **Верно!**\n{result['explanation']}")
    else:
        send(chat_id, f"❌ **Правильный ответ: {LETTERS[result['correct']]}**\n{result['explanation']}")
    if not result["finished"]:
        send_question(chat_id, result["quiz"], index + 1)
        return
    send(chat_id, f"🏁 **Результат: {result['score']} из {result['total']}**\n\n" +
         ("Отлично! Эти ошибки отмечены как проработанные 💪" if result["passed"]
          else "Разбери пояснения выше и попробуй ещё раз — ошибки пока остаются в работе."), MENU)


def show_progress(session, user, chat_id):
    stats = db.independence(session, user)
    if stats["index"] is None:
        index_line = "появится после первой решённой задачи (кнопка «✔ Проверить решение»)"
    else:
        index_line = f"**{stats['index']} из 100**"
    lines = [
        "📊 **Твой прогресс**", "",
        f"Индекс самостоятельности: {index_line}",
        f"Решено задач: {stats['solved']}, сам и с первой попытки: {stats['first_try']}",
    ]
    if stats["mistake_types"]:
        lines += ["", "**Ошибки в работе:**"]
        for error_type, count in sorted(stats["mistake_types"].items(), key=lambda x: -x[1]):
            lines.append(f"• {ERROR_TYPES.get(error_type, error_type)} — {count}")
    lines += ["", "Как считается индекс: задача, решённая сама с первой проверки, — 100 баллов; "
                  "каждая неудачная проверка −20, каждая подсказка −15. Среднее за последние 10 задач."]
    send(chat_id, "\n".join(lines), [[button("🌐 Веб-кабинет", "web")]] + MENU)


# ---------- класс ----------

def show_classroom(session, user, chat_id):
    """Ученику — его класс и задания; учителю — его классы с кодами; новичку — как вступить или создать."""
    lines, rows = [], []
    info = tutor.student_classroom(session, user)
    if info:
        lines.append(f"🏫 Ты в классе «**{info['name']}**»"
                     + (f", учитель — {info['teacher']}" if info["teacher"] else ""))
        if info["assignments"]:
            lines.append("\n**Задания:**")
            for a in info["assignments"][:8]:
                status = f"✅ решено {a['solved']}" if a["solved"] else ("▶️ начато" if a["started"] else "🆕 новое")
                lines.append(f"• {a['topic']} — {status}")
                rows.append([button(f"{a['topic'][:40]}", f"assign:{a['id']}")])
        else:
            lines.append("Заданий пока нет — учитель пришлёт их сюда.")
        rows.append([button("🚪 Выйти из класса", "leave_class")])

    teaching = db.teacher_classrooms(session, user)
    if teaching:
        lines.append("\n👩‍🏫 **Твои классы как учителя:**")
        for c in teaching:
            lines.append(f"• {c.name} — код **{c.code}**, учеников: {len(db.class_students(session, c))}")
        lines.append("Сводка класса, ошибки учеников и выдача заданий — в веб-кабинете.")
        rows.append([button("🌐 Веб-кабинет", "web")])

    if not info:
        lines.insert(0, "Вступи в класс, и учитель сможет выдавать тебе задания, а ты — видеть их здесь."
                        if not teaching else "")
        rows.insert(0, [button("🔑 Вступить по коду", "join")])
    rows.append([button("👩‍🏫 Создать класс (я учитель)", "new_class")])
    send(chat_id, "\n".join(line for line in lines if line) or "🏫 Класс", rows + [[MENU_BUTTON]])


# ---------- маршрутизация ----------

def handle_message(session, user, chat_id, message):
    text = message['body'].get('text') or ''
    image_url = find_image_url(message)
    if not text and not image_url:                            # стикер, голосовое и т. п.
        send(chat_id, "Я понимаю текст и фото задач 🙂 Напиши вопрос словами или пришли фото.")
        return

    command = text.strip().lower()
    if command == "/start":
        # Новый разговор, но не плодим пустые: если текущий и так пустой — остаёмся в нём
        space = db.current_space(session, user)
        if space.messages or space.topic != tutor.FREE_TOPIC:
            db.new_space(session, user)
        session.commit()
        if user.grade is None:
            ask_grade(session, user, chat_id, greeting=True)
        else:
            send(chat_id, f"С возвращением{', ' + user.name if user.name else ''}! 👋\n"
                          "Открой тему, напиши вопрос или пришли фото задачи.", MENU)
        return
    if command in ("/menu", "меню"):
        user.mode = "chat"
        session.commit()
        send(chat_id, "☰ **Меню**", MENU)
        return
    if command in ("/help", "помощь"):
        send(chat_id, HELP, MENU)
        return
    if command == "/privacy":
        send(chat_id, PRIVACY, MENU)
        return
    if command == "/delete":
        send(chat_id, "Удалить **все** твои данные: переписку, темы, ошибки, тесты и индекс? "
                      "Вернуть их будет нельзя.",
             [[button("🗑 Да, удалить всё", "delete_confirm"), button("↩️ Отмена", "cancel")]])
        return

    if user.mode == "topic" and text:
        start_topic(session, user, chat_id, text.strip())
    elif user.mode == "join" and text:
        user.mode = "chat"
        classroom = tutor.join_classroom(session, user, text)
        send(chat_id, f"Готово! Ты в классе «**{classroom.name}**» 🎉\n"
                      "Когда учитель выдаст задание, я пришлю его сюда.", MENU)
    elif user.mode == "new_class" and text:
        user.mode = "chat"
        classroom = tutor.create_classroom(session, user, text)
        send(chat_id, f"Класс «**{classroom.name}**» создан ✅\n\n"
                      f"Код для учеников: **{classroom.code}**\n"
                      "Ученики вступают так: «🏫 Мой класс» → «Вступить по коду».\n\n"
                      "Сводку класса, ошибки учеников и выдачу заданий смотри в веб-кабинете.",
             [[button("🌐 Веб-кабинет", "web")], [MENU_BUTTON]])
    elif user.mode == "check":
        check_in_space(session, user, chat_id, text, image_url)
    else:
        reply_in_space(session, user, chat_id, text, image_url)


# Кнопки, которые сами переводят бота в режим ожидания; любая другая кнопка этот режим сбрасывает
MODE_BUTTONS = ("check", "new_topic", "join", "new_class")


def handle_button(session, user, chat_id, payload):
    if not payload.startswith(MODE_BUTTONS) and user.mode != "chat":
        user.mode = "chat"          # ученик передумал: следующее сообщение — обычный вопрос
        session.commit()

    if payload == "menu" or payload == "cancel":
        send(chat_id, "☰ **Меню**", MENU)
    elif payload == "help":
        send(chat_id, HELP, MENU)
    elif payload == "delete_confirm":
        db.delete_user_data(session, user)
        session.commit()
        send(chat_id, "Готово: все твои данные удалены 🗑\nЕсли захочешь вернуться — просто напиши /start.")
    elif payload == "level":
        ask_grade(session, user, chat_id)
    elif payload.startswith("grade:"):
        user.grade = int(payload.split(":")[1])
        session.commit()
        ask_goal(session, user, chat_id)
    elif payload.startswith("goal:"):
        user.goal = payload.split(":")[1]
        session.commit()
        profile_done(session, user, chat_id)
    elif payload == "check":
        ask_for_solution(session, user, chat_id)
    elif payload == "hint":
        give_hint(session, user, chat_id)
    elif payload == "next":
        give_next_task(session, user, chat_id)
    elif payload == "quiz":
        start_quiz(session, user, chat_id)
    elif payload == "class":
        show_classroom(session, user, chat_id)
    elif payload == "join":
        user.mode = "join"
        session.commit()
        send(chat_id, "Напиши код класса, который дал учитель (6 символов, например K7M2QX).",
             [[button("↩️ Отмена", "cancel")]])
    elif payload == "new_class":
        user.mode = "new_class"
        session.commit()
        send(chat_id, "Как назвать класс? Например, «9 Б, алгебра».", [[button("↩️ Отмена", "cancel")]])
    elif payload == "leave_class":
        tutor.leave_classroom(session, user)
        send(chat_id, "Ты вышел из класса.", MENU)
    elif payload.startswith("assign:"):
        send(chat_id, "⏳ Открываю задание…")
        typing(chat_id)
        space, text = tutor.start_assignment(session, user, int(payload.split(":")[1]))
        send(chat_id, text, task_keyboard(space))
    elif payload == "web":
        code = db.new_login_code(session, user)
        session.commit()
        send(chat_id, f"🌐 Веб-кабинет: {WEB_URL}\n\nКод для входа: **{code}**\n"
                      "Код одноразовый и действует 10 минут. Никому его не пересылай.")
    elif payload == "progress":
        show_progress(session, user, chat_id)
    elif payload.startswith("qa:"):
        _, quiz_id, index, option = payload.split(":")
        answer_question(session, user, chat_id, int(quiz_id), int(index), int(option))
    elif payload == "new_topic":
        ask_for_topic(session, user, chat_id)
    elif payload == "my_topics":
        show_my_topics(session, user, chat_id)
    elif payload.startswith("topic:"):
        start_topic(session, user, chat_id, TOPICS[int(payload.split(":")[1])])
    elif payload.startswith("space:"):
        open_space(session, user, chat_id, int(payload.split(":")[1]))


def handle_update(update):
    kind = update["update_type"]
    if kind == "message_created":
        message = update["message"]
        sender = message['sender']
        if sender.get('is_bot'):
            return
    elif kind == "message_callback":
        callback = update["callback"]
        answer_callback(callback["callback_id"])
        sender = callback["user"]
        message = update["message"]                  # сообщение, под которым нажали кнопку
    elif kind == "bot_started":
        # Ученик впервые открыл бота и нажал «Начать»
        sender = update["user"]
        message = {"recipient": {"chat_id": update["chat_id"]}, "body": {"text": "/start"}}
        kind = "message_created"
    else:
        return

    # СОКРАТ — личный наставник: в групповых чатах и каналах молчим,
    # иначе в чате класса бот начнёт отвечать на каждое сообщение
    if message['recipient'].get('chat_type', 'dialog') != 'dialog':
        return

    chat_id = message['recipient']['chat_id']
    with chat_lock(chat_id), Session(engine) as session:
        user = db.get_user(session, sender['user_id'], sender.get('first_name', ''))
        try:
            if kind == "message_created":
                handle_message(session, user, chat_id, message)
            else:
                handle_button(session, user, chat_id, callback.get("payload") or "")
        except tutor.TutorError as e:
            # Понятная ситуация («подсказки кончились», «нет ошибок для теста») — объясняем ученику
            send(chat_id, str(e), task_keyboard(db.current_space(session, user)))
        except Exception as e:
            print("Ошибка при ответе:", repr(e))
            try:
                send(chat_id, "Наставник задумался 🤔 Попробуй ещё раз через минуту.", [[MENU_BUTTON]])
            except Exception:
                pass                          # если и это не отправилось — просто идём дальше


# ---------- главный цикл ----------

# Учеников обслуживаем параллельно: пока ИИ думает над ответом одному, другие не ждут.
# А сообщения ОДНОГО ученика — строго по очереди, чтобы ответы не перепутались.
pool = ThreadPoolExecutor(max_workers=8)
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def chat_lock(chat_id):
    with _locks_guard:
        return _locks.setdefault(chat_id, threading.Lock())


def safe_handle(update):
    try:
        handle_update(update)
    except Exception as e:
        print("Ошибка обработки обновления:", repr(e))


def run_bot():
    marker = None  # номер последнего обработанного обновления
    print("Бот запущен")
    while True:
        # 1. Получаем новые сообщения. Если нет связи — ждём и пробуем снова
        params = {"timeout": 30}
        if marker is not None:
            params["marker"] = marker
        try:
            resp = httpx.get(f"{API}/updates", headers=HEADERS, params=params, verify=CERT, timeout=40)
            data = resp.json()
        except Exception as e:
            print("Нет связи с MAX:", e)
            time.sleep(5)
            continue                          # к следующему кругу while
        marker = data.get("marker", marker)

        # 2. Каждое обновление — в отдельный поток: сообщение или нажатие кнопки
        for update in data.get("updates", []):
            pool.submit(safe_handle, update)


if __name__ == "__main__":
    run_bot()
