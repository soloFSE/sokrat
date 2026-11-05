"""Общие настройки тестов: отдельная временная база и тестовый токен бота.
Настоящие ключи и база ученика в тестах не используются."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)                                   # чтобы находился сертификат Минцифры

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["BOT_TOKEN"] = "test-bot-token"
