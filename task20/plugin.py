"""Плагин для задания 20."""

import logging
from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers

logger = logging.getLogger(__name__)

class Task20Plugin(BotPlugin):
    code = "task20"
    title = "Задание 20 (Суждения)"
    menu_priority = 16  # После task19
    
    async def post_init(self, app):
        """Инициализация данных для задания 20."""
        try:
            await handlers.init_task20_data()
            logger.info(f"Task20 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task20 data: {e}")
    
    def entry_handler(self):
        """Возвращает обработчик для входа из главного меню."""
        return CallbackQueryHandler(
            handlers.entry_from_menu,
            pattern=f"^choose_{self.code}$"
        )
    
    def register(self, app):
        """Регистрация обработчиков в приложении."""
        # Здесь будет ConversationHandler по аналогии с task19
        pass

# Экспортируем плагин
plugin = Task20Plugin()