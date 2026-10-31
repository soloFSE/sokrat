"""Настройки приложения из переменных окружения (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Токен бота MAX (business.max.ru → Чат-боты → Настройки)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MAX_API_URL = os.getenv("MAX_API_URL", "https://platform-api2.max.ru")

# Публичный HTTPS-адрес мини-приложения (нужен для кнопки «Открыть» и вебхука)
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

# Режим получения обновлений бота: polling (по умолчанию) или webhook
BOT_MODE = os.getenv("BOT_MODE", "polling")

# Yandex AI Studio
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
YANDEX_MODEL = os.getenv("YANDEX_MODEL", "yandexgpt/latest")

# Режим разработки: позволяет открыть мини-приложение в обычном браузере без MAX
DEV_MODE = os.getenv("DEV_MODE", "0") == "1"

DB_PATH = Path(os.getenv("DB_PATH", ROOT / "data" / "sokrat.db"))
CA_BUNDLE = ROOT / "certs" / "russian_trusted_ca.pem"
WEBAPP_DIR = ROOT / "webapp"
