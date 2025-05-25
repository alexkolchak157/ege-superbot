# core/app.py (исправленный)
import sys
import os

# Добавляем корневую папку проекта в sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from telegram.ext import Application, CommandHandler
from core.plugin_loader import discover_plugins, build_main_menu, PLUGINS
from core.menu_handlers import register_global_handlers

# Попробуем импортировать токен из test_part или task24
try:
    from test_part.config import BOT_TOKEN
except ImportError:
    try:
        from task24.config import BOT_TOKEN
    except ImportError:
        import os
        BOT_TOKEN = os.getenv("TG_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        if not BOT_TOKEN:
            raise ValueError("Не найден BOT_TOKEN! Проверьте файлы config.py или переменные окружения.")

async def start(update, context):
    """Главная команда /start - показывает меню плагинов."""
    await update.message.reply_text(
        "👋 Что хотите потренировать?",
        reply_markup=build_main_menu(),
    )

def main():
    """Основная функция запуска бота."""
    
    print("🔍 Обнаруживаем плагины...")
    discover_plugins()
    
    print("⚙️ Создаём приложение...")
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(lambda a: a.bot.delete_webhook(drop_pending_updates=True))
        .build()
    )

    print("🌐 Регистрируем глобальные обработчики...")
    register_global_handlers(app)
    
    print("📝 Регистрируем команду /start...")
    app.add_handler(CommandHandler("start", start))

    print("🔌 Регистрируем плагины...")
    for plugin in PLUGINS:
        app.add_handler(plugin.entry_handler())
        plugin.register(app)

    print("🚀 Бот запущен! Нажмите Ctrl+C для остановки.")
    app.run_polling()

if __name__ == "__main__":
    main()