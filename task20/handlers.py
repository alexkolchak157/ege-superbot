"""Обработчики для задания 20."""

import logging
import os
import json
from typing import Optional, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import states
from .evaluator import Task20AIEvaluator, StrictnessLevel, EvaluationResult
from datetime import datetime

logger = logging.getLogger(__name__)

# Глобальное хранилище для данных задания 20
task20_data = {}

# Инициализируем evaluator
evaluator = Task20AIEvaluator(strictness=StrictnessLevel.STANDARD)

async def init_task20_data():
    """Инициализация данных для задания 20."""
    global task20_data
    
    data_file = os.path.join(os.path.dirname(__file__), "task20_topics.json")
    
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        
        # Обработка данных по аналогии с task19
        all_topics = []
        for block_name, block in raw.get("blocks", {}).items():
            for topic in block.get("topics", []):
                topic["block"] = block_name
                all_topics.append(topic)
        
        task20_data = raw
        task20_data["topics"] = all_topics
        
        logger.info(f"Loaded {len(all_topics)} topics for task20")
    except Exception as e:
        logger.error(f"Failed to load task20 data: {e}")
        task20_data = {"topics": [], "blocks": {}}

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

# Другие обработчики по аналогии с task19...