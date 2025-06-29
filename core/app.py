import sys
import os
import logging
from telegram.ext import Application, CommandHandler
from core.plugin_loader import discover_plugins, build_main_menu, PLUGINS
from core.menu_handlers import register_global_handlers
from core.menu_handlers import handle_to_main_menu
from core.admin_tools import register_admin_handlers
from core.config import BOT_TOKEN
from core import db
from core.error_handler import register_error_handler
from core.state_validator import state_validator  # Добавленный импорт

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
    
    # Логируем статус валидатора состояний
    logger.info(f"State validator initialized with {len(state_validator.allowed_transitions)} state transitions")

async def post_shutdown(application: Application) -> None:
    """Выполняется при завершении приложения."""
    await db.close_db()
    
    # Выводим статистику переходов состояний
    stats = state_validator.get_stats()
    logger.info(f"State transitions statistics: {stats['total_transitions']} total transitions")
    if stats['top_transitions']:
        logger.info("Top state transitions:")
        for transition, count in stats['top_transitions'][:5]:
            logger.info(f"  {transition}: {count} times")

async def start(update, context):
    """Главная команда /start."""
    await update.message.reply_text(
        "👋 Добро пожаловать! Что хотите потренировать?",
        reply_markup=build_main_menu(),
    )
    context.user_data.clear()
    
    # Очищаем состояние пользователя в валидаторе
    if update.effective_user:
        state_validator.clear_state(update.effective_user.id)

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
    
    # Добавляем команду для просмотра статистики состояний (для админов)
    async def state_stats(update, context):
        """Показывает статистику переходов состояний."""
        from core.admin_tools import admin_manager
        
        if not admin_manager.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Эта команда доступна только администраторам")
            return
        
        stats = state_validator.get_stats()
        text = f"📊 <b>Статистика переходов состояний</b>\n\n"
        text += f"Всего переходов: {stats['total_transitions']}\n"
        text += f"Уникальных переходов: {stats['unique_transitions']}\n"
        text += f"Активных пользователей: {stats['active_users']}\n\n"
        
        if stats['top_transitions']:
            text += "<b>Топ переходов:</b>\n"
            for transition, count in stats['top_transitions'][:10]:
                text += f"• {transition}: {count}\n"
        
        await update.message.reply_text(text, parse_mode='HTML')
    
    app.add_handler(CommandHandler("state_stats", state_stats))
    
    print("🔌 Регистрируем плагины...")
    for plugin in PLUGINS:
        plugin.register(app)
    
    register_error_handler(app)
    
    print("✅ Валидатор состояний активирован")
    print("🚀 Бот запущен! Нажмите Ctrl+C для остановки.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()