"""Загрузчик плагинов для бота."""

import importlib
import pkgutil
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.plugin_base import BotPlugin

# Глобальный список плагинов
PLUGINS: List[BotPlugin] = []


def discover_plugins() -> None:
    """Ищем модули *.plugin.py в корне проекта."""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("Starting plugin discovery...")
    
    for mod in pkgutil.iter_modules():
        # Добавляем task25 в список модулей
        if mod.name in ("test_part", "task24", "task19", "task20", "task25"):
            try:
                logger.info(f"Loading plugin: {mod.name}")
                plugin_module = importlib.import_module(f"{mod.name}.plugin")
                PLUGINS.append(plugin_module.plugin)
                logger.info(f"Successfully loaded: {plugin_module.plugin.title}")
            except Exception as e:
                logger.error(f"Failed to load plugin {mod.name}: {e}")
    
    PLUGINS.sort(key=lambda p: p.menu_priority)
    logger.info(f"Loaded {len(PLUGINS)} plugins: {[p.title for p in PLUGINS]}")


def build_main_menu() -> InlineKeyboardMarkup:
    """Строит главное меню из всех загруженных плагинов."""
    import logging
    logger = logging.getLogger(__name__)
    
    if not PLUGINS:
        logger.warning("No plugins loaded for main menu!")
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Нет доступных модулей", callback_data="no_plugins")
        ]])
    
    buttons = []
    for p in PLUGINS:
        logger.debug(f"Adding menu button for plugin: {p.code} - {p.title}")
        buttons.append([InlineKeyboardButton(
            p.title,
            callback_data=f"choose_{p.code}"
        )])
    
    logger.info(f"Main menu built with {len(buttons)} buttons")
    return InlineKeyboardMarkup(buttons)
    
# Добавьте эту функцию в конец файла core/plugin_loader.py

def load_modules(application):
    """Загружает и регистрирует все плагины в приложении."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Сначала ищем все плагины
    discover_plugins()
    
    # Затем регистрируем каждый плагин
    for plugin in PLUGINS:
        try:
            logger.info(f"Registering plugin: {plugin.title}")
            plugin.register(application)
            
            # Если у плагина есть post_init, добавляем его в очередь
            if hasattr(plugin, 'post_init'):
                application.post_init(plugin.post_init)
                
        except Exception as e:
            logger.error(f"Failed to register plugin {plugin.code}: {e}")
    
    logger.info(f"Successfully registered {len(PLUGINS)} plugins")
    
    # Регистрируем обработчик главного меню
    from telegram import Update
    from telegram.ext import CommandHandler, CallbackQueryHandler
    
    async def show_main_menu(update: Update, context):
        """Показывает главное меню."""
        menu = build_main_menu()
        text = "👋 Выберите раздел для подготовки к ЕГЭ:"
        
        if update.message:
            await update.message.reply_text(text, reply_markup=menu)
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=menu)
    
    # Добавляем команду /menu для показа главного меню
    application.add_handler(CommandHandler("menu", show_main_menu))
    
    # Добавляем обработчик для кнопки "Главное меню"
    application.add_handler(
        CallbackQueryHandler(show_main_menu, pattern="^main_menu$")
    )