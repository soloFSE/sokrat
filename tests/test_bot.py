"""Поведение бота без MAX и без ИИ: сообщения перехватываем, ответы ИИ подменяем."""
import pytest

import ai
import bot


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(bot, "send", lambda chat_id, text, buttons=None: messages.append((chat_id, text)))
    monkeypatch.setattr(bot, "typing", lambda chat_id: None)
    monkeypatch.setattr(bot, "answer_callback", lambda callback_id: None)
    monkeypatch.setattr(ai, "ask", lambda *args, **kwargs: "ответ наставника")
    return messages


def message(text, chat_type="dialog", user_id=101, chat_id=5):
    return {"update_type": "message_created",
            "message": {"sender": {"user_id": user_id, "first_name": "Аня"},
                        "recipient": {"chat_id": chat_id, "chat_type": chat_type},
                        "body": {"text": text}}}


def test_bot_answers_in_private_dialog(sent):
    bot.handle_update(message("Что такое дискриминант?"))
    assert sent, "в личном диалоге бот должен ответить"


@pytest.mark.parametrize("chat_type", ["chat", "channel"])
def test_bot_is_silent_in_group_chats(sent, chat_type):
    bot.handle_update(message("Всем привет!", chat_type=chat_type))
    assert sent == [], "в чате класса бот не должен отвечать на каждое сообщение"


def test_bot_ignores_other_bots(sent):
    update = message("я тоже бот")
    update["message"]["sender"]["is_bot"] = True
    bot.handle_update(update)
    assert sent == []
