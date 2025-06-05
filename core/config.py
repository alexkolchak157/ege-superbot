import os
from dotenv import load_dotenv

load_dotenv()

# Поддержка обоих вариантов переменных токена
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_TOKEN")
if not BOT_TOKEN:
    print("!!! ВНИМАНИЕ: Не найден токен бота TELEGRAM_BOT_TOKEN или TG_TOKEN в .env файле или переменной окружения.")
    raise ValueError("Ошибка: Необходим TELEGRAM_BOT_TOKEN или TG_TOKEN в .env файле или переменных окружения")

# ID канала для проверки подписки
# Для публичных каналов используйте @username
# Для приватных каналов используйте числовой ID (например, -1001234567890)
REQUIRED_CHANNEL = "@obshestvonapalcah"  # Убедитесь, что канал существует

# Пути к файлам
QUESTIONS_FILE = os.getenv("QUESTIONS_FILE", "data/questions.json")
DATABASE_FILE = os.getenv("DATABASE_FILE", "quiz_async.db")
STORAGE_DATABASE_FILE = os.getenv("STORAGE_DATABASE_FILE", "fsm_storage.db")
REMINDER_INACTIVITY_DAYS = int(os.getenv("REMINDER_INACTIVITY_DAYS", 3))