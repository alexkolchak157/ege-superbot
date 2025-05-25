from typing import List, Optional
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# аккуратно импортируем словарь "читаемые названия тем"
try:
    from .topic_data import TOPIC_NAMES
except ImportError:      # если файл ещё не приехал в пакет – просто работаем с id тем
    logging.error("Не найден файл topic_data.py или словарь TOPIC_NAMES в нём.")
    TOPIC_NAMES: dict = {}

# ---------------------------------------------------------------------------
# 1. ГЛАВНОЕ МЕНЮ ПЛАГИНОВ
# ---------------------------------------------------------------------------

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Две кнопки – переходы к плагинам через callback_data choose_<code>."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Тестовая часть", callback_data="choose_test_part"),
            InlineKeyboardButton("Задание 24",   callback_data="choose_task24"),
        ]
    ])

# ---------------------------------------------------------------------------
# 2. ВЫБОР РЕЖИМА ДЛЯ ТЕСТ-БОТА
# ---------------------------------------------------------------------------

def get_initial_choice_keyboard() -> InlineKeyboardMarkup:
    """Стартовая клавиатура: выбираем, как задавать вопросы."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 По номеру ЕГЭ",          callback_data="mode:choose_exam_num")],
        [InlineKeyboardButton("📚 По блоку тем",            callback_data="mode:choose_topic")],
        [InlineKeyboardButton("🎲 Случайные вопросы (все)", callback_data="mode:random")],
    ])

# ---------------------------------------------------------------------------
# 3. БЛОКИ, РЕЖИМЫ, ТЕМЫ
# ---------------------------------------------------------------------------

def get_blocks_keyboard(blocks: List[str]) -> Optional[InlineKeyboardMarkup]:
    if not blocks:
        return None
    buttons, row = [], []
    for i, block in enumerate(blocks, 1):
        row.append(InlineKeyboardButton(block, callback_data=f"block:{block}"))
        if i % 2 == 0:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="to_menu")])
    return InlineKeyboardMarkup(buttons)

def get_mode_keyboard(block_name: str) -> InlineKeyboardMarkup:
    """Выбор режима *внутри* конкретного блока."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайные из блока", callback_data="mode:random")],
        [InlineKeyboardButton("📚 По теме блока",      callback_data="mode:choose_topic")],
        [InlineKeyboardButton("⬅️ Назад к блокам",     callback_data="to_blocks")],
    ])

def get_topics_keyboard(block_name: str, topics: List[str]) -> Optional[InlineKeyboardMarkup]:
    if not topics:
        return None
    buttons = [[InlineKeyboardButton(TOPIC_NAMES.get(t, t), callback_data=f"topic:{t}")]
               for t in topics]
    buttons.append([InlineKeyboardButton("⬅️ Назад к режиму", callback_data="to_mode")])
    return InlineKeyboardMarkup(buttons)

def get_exam_number_keyboard(numbers: List[int]) -> Optional[InlineKeyboardMarkup]:
    if not numbers:
        return None
    buttons, row = [], []
    for i, n in enumerate(sorted(numbers), 1):
        row.append(InlineKeyboardButton(str(n), callback_data=f"examnum:{n}"))
        if i % 6 == 0:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="to_menu")])
    return InlineKeyboardMarkup(buttons)

# ---------------------------------------------------------------------------
# 4. ПОСЛЕ ОТВЕТА – ЧТО ДЕЛАТЬ ДАЛЬШЕ?
# ---------------------------------------------------------------------------

def get_after_answer_keyboard(last_mode: str = "random") -> InlineKeyboardMarkup:
    """Клавиатура после проверки ответа.
    last_mode передаётся из quiz_handlers, чтобы показывать корректную
    подпись основной кнопки (ещё вопрос / ещё по теме и т.д.)."""

    main_button: InlineKeyboardButton
    if last_mode == "topic":
        main_button = InlineKeyboardButton("➡️ Ещё вопрос по теме", callback_data="next_topic")
    elif last_mode == "exam_num":
        main_button = InlineKeyboardButton("➡️ Следующий номер", callback_data="next_random")
    else:  # random
        main_button = InlineKeyboardButton("➡️ Ещё случайный", callback_data="next_random")

    return InlineKeyboardMarkup([
        [main_button],
        [InlineKeyboardButton("🔄 Сменить тему / режим", callback_data="change_topic")],
        [InlineKeyboardButton("🏠 Главное меню",          callback_data="to_menu")],
    ])

# ---------------------------------------------------------------------------
# 5. НАВИГАЦИЯ ПО ОШИБКАМ (разбор)
# ---------------------------------------------------------------------------

def get_mistakes_nav_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Следующая ошибка", callback_data="mistake:next")],
        [InlineKeyboardButton("⏩ Пропустить",        callback_data="mistake:skip")],
        [InlineKeyboardButton("🚪 Закончить разбор",  callback_data="mistake:exit")],
    ])
