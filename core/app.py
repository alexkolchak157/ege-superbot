import sys
import os
import logging
from telegram.ext import Application, CommandHandler
from core.plugin_loader import discover_plugins, build_main_menu, PLUGINS
from core.menu_handlers import register_global_handlers
from core.admin_tools import register_admin_handlers
from core.config import BOT_TOKEN
from core import db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def post_init(application: Application) -> None:
    """Инициализация после запуска приложения."""
    logger.info("Инициализация БД...")
    await db.init_db()
    
    # Загрузка данных для плагинов
    for plugin in PLUGINS:
        if hasattr(plugin, 'post_init'):
            await plugin.post_init(application)
    
    logger.info("Инициализация завершена")

async def post_shutdown(application: Application) -> None:
    """Выполняется при завершении приложения."""
    await db.close_db()

async def start(update, context):
    """Главная команда /start."""
    await update.message.reply_text(
        "👋 Добро пожаловать! Что хотите потренировать?",
        reply_markup=build_main_menu(),
    )
    context.user_data.clear()

def main():
    """Основная функция запуска бота."""
    
    print("🔍 Обнаруживаем плагины...")
    discover_plugins()
    
    print("⚙️ Создаём приложение...")
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    print("🌐 Регистрируем глобальные обработчики...")
    register_global_handlers(app)

    print("🔧 Регистрируем админские обработчики...")
    register_admin_handlers(app)
    
    print("📝 Регистрируем команду /start...")
    app.add_handler(CommandHandler("start", start))

    print("🔌 Регистрируем плагины...")
    for plugin in PLUGINS:
        plugin.register(app)

    print("🚀 Бот запущен! Нажмите Ctrl+C для остановки.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
