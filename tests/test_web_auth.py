"""Вход в веб-версию: подпись данных MAX, срок их действия и токен сессии."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import web


def make_init_data(user_id=777, auth_date=None, token="test-bot-token", tamper=False):
    """Собирает initData так же, как это делает MAX, и подписывает его."""
    data = {"user": json.dumps({"id": user_id, "first_name": "Аня"}), "query_id": "q1"}
    if auth_date is not None:
        data["auth_date"] = str(auth_date)
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if tamper:
        data["user"] = json.dumps({"id": 999, "first_name": "Чужой"})
    return urlencode(data)


def test_fresh_init_data_is_accepted():
    assert web.user_from_init_data(make_init_data(auth_date=int(time.time()))) == 777


def test_init_data_in_milliseconds_is_accepted():
    assert web.user_from_init_data(make_init_data(auth_date=int(time.time() * 1000))) == 777


def test_init_data_without_date_is_rejected():
    assert web.user_from_init_data(make_init_data(auth_date=None)) is None


def test_old_init_data_is_rejected():
    two_days_ago = int(time.time()) - 2 * 24 * 3600
    assert web.user_from_init_data(make_init_data(auth_date=two_days_ago)) is None


def test_tampered_init_data_is_rejected():
    assert web.user_from_init_data(make_init_data(auth_date=int(time.time()), tamper=True)) is None


def test_init_data_signed_by_other_bot_is_rejected():
    assert web.user_from_init_data(make_init_data(auth_date=int(time.time()), token="other")) is None


def test_session_token_roundtrip_and_forgery():
    token = web.sign(42)
    assert web.user_from_token(token) == 42
    assert web.user_from_token("43." + token.split(".")[1]) is None
    assert web.user_from_token("garbage") is None


# ---------- защита входа по коду от перебора ----------

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import db


def test_login_code_brute_force_is_blocked(monkeypatch):
    monkeypatch.setattr(web, "_login_fails", web.defaultdict(web.deque))
    client = TestClient(web.app)
    with Session(db.engine) as session:
        code = db.new_login_code(session, db.get_user(session, 8001, "Аня"))
        session.commit()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(web.LOGIN_FAILS_PER_IP):
        assert client.post("/api/login", json={"code": wrong}).status_code == 400
    # после 5 неверных попыток даже правильный код с этого адреса не принимается
    assert client.post("/api/login", json={"code": code}).status_code == 429


def test_login_with_right_code_works_once(monkeypatch):
    monkeypatch.setattr(web, "_login_fails", web.defaultdict(web.deque))
    client = TestClient(web.app)
    with Session(db.engine) as session:
        code = db.new_login_code(session, db.get_user(session, 8002, "Тимур"))
        session.commit()
    first = client.post("/api/login", json={"code": code})
    assert first.status_code == 200 and web.user_from_token(first.json()["token"]) == 8002
    assert client.post("/api/login", json={"code": code}).status_code == 400     # код одноразовый
