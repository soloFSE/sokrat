"""Запуск СОКРАТа одной командой: бот MAX + веб-кабинет.

    python main.py

Бот работает в отдельном потоке и опрашивает MAX, веб-кабинет отвечает на http://localhost:8000.
Оба пользуются одной базой sokrat.db, поэтому прогресс ученика общий.
"""
import os
import threading

import uvicorn

from bot import run_bot
from web import app

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
