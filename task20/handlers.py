"""Обработчики для задания 20."""

import logging
import os
import json
from typing import Optional, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import states

logger = logging.getLogger(__name__)

# Глобальное хранилище для данных задания 20
task20_data = {}

async def init_task20_data():
    """Инициализация данных для задания 20."""
    global task20_data
    
    # Пока используем заглушку
    task20_data = {
        "topics": [],
        "blocks": {}
    }
    logger.info("Task20 data initialized (stub)")

async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 20 из главного меню."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📝 <b>Задание 20</b>\n\n"
        "В этом задании нужно сформулировать суждения (аргументы) "
        "абстрактного характера с элементами обобщения.\n\n"
        "⚠️ <b>Важно:</b> НЕ приводите конкретные примеры!\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t20_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t20_theory")],
        [InlineKeyboardButton("🏦 Банк суждений", callback_data="t20_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t20_progress")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="t20_settings")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def cmd_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task20."""
    text = (
        "📝 <b>Задание 20</b>\n\n"
        "В этом задании нужно сформулировать суждения (аргументы) "
        "абстрактного характера с элементами обобщения.\n\n"
        "⚠️ <b>Важно:</b> НЕ приводите конкретные примеры!\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t20_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t20_theory")],
        [InlineKeyboardButton("🏦 Банк суждений", callback_data="t20_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t20_progress")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="t20_settings")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

# Заглушки для остальных обработчиков
async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🚧 <b>Режим практики в разработке</b>\n\n"
        "Здесь вы сможете:\n"
        "• Выбрать тему для тренировки\n"
        "• Написать свои суждения\n"
        "• Получить оценку и обратную связь",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
        ]]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим теории."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📚 <b>Теория по заданию 20</b>\n\n"
        "<b>Ключевые отличия от задания 19:</b>\n"
        "• НЕ нужны конкретные примеры\n"
        "• Требуются абстрактные суждения\n"
        "• Используйте обобщающие слова\n\n"
        "<b>Полезные конструкции:</b>\n"
        "• способствует...\n"
        "• приводит к...\n"
        "• влияет на...\n"
        "• определяет...\n"
        "• формирует...",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
        ]]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Банк суждений."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🏦 <b>Банк суждений</b>\n\n"
        "Здесь будут примеры правильных суждений по разным темам.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
        ]]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Прогресс пользователя."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📊 <b>Ваш прогресс</b>\n\n"
        "Статистика будет доступна после начала практики.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
        ]]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "⚙️ <b>Настройки</b>\n\n"
        "Здесь можно будет настроить уровень строгости проверки.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
        ]]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 20."""
    return await entry_from_menu(update, context)

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    from core.plugin_loader import build_main_menu
    
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👋 Что хотите потренировать?",
        reply_markup=build_main_menu()
    )
    
    return ConversationHandler.END

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик."""
    query = update.callback_query
    await query.answer()
    return None

# Заглушки для остальных обработчиков
async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await practice_mode(update, context)

async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await practice_mode(update, context)

async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await practice_mode(update, context)

async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await practice_mode(update, context)

async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await practice_mode(update, context)

async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await practice_mode(update, context)

async def bank_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await examples_bank(update, context)

async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await examples_bank(update, context)

async def set_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await settings_mode(update, context)

async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await my_progress(update, context)

async def export_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await my_progress(update, context)

async def choose_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await practice_mode(update, context)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя."""
    await update.message.reply_text(
        "Ваш ответ получен. Функция проверки в разработке.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")
        ]])
    )
    return states.CHOOSING_MODE

async def handle_bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поиска в банке."""
    return await examples_bank(update, context)

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    return await back_to_main_menu(update, context)
