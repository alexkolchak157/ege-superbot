# test_part/keyboards.py (исправленная версия)

from typing import List, Optional
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Импортируем общие утилиты
from .utils import TestPartCallbackData as CallbackData

try:
    from .topic_data import TOPIC_NAMES
except ImportError:
    logging.error("Не найден файл topic_data.py или словарь TOPIC_NAMES в нём.")
    TOPIC_NAMES: dict = {}

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню плагинов."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Тестовая часть", callback_data=CallbackData.get_plugin_entry("test_part")),
            InlineKeyboardButton("Задание 24", callback_data=CallbackData.get_plugin_entry("task24")),
        ]
    ])

def get_initial_choice_keyboard() -> InlineKeyboardMarkup:
    """Стартовая клавиатура: выбираем, как задавать вопросы."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 По номеру ЕГЭ", callback_data="initial:select_exam_num_mode")],
        [InlineKeyboardButton("📚 По блоку тем", callback_data="initial:select_block_mode")],
        [InlineKeyboardButton("🎲 Случайные вопросы (все)", callback_data="initial:select_random_all")],
        [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="initial:select_mistakes_mode")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])

def get_blocks_keyboard(blocks: List[str]) -> Optional[InlineKeyboardMarkup]:
    if not blocks:
        return None
    
    buttons = []
    row = []
    
    for i, block in enumerate(blocks, 1):
        button = InlineKeyboardButton(
            text=block, 
            callback_data=f"block:select:{block}"
        )
        row.append(button)
        
        if i % 2 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(
        "⬅️ Назад", 
        callback_data="block:back_to_initial"
    )])
    
    return InlineKeyboardMarkup(buttons) 

def get_mode_keyboard(block_name: str) -> InlineKeyboardMarkup:
    """Выбор режима *внутри* конкретного блока."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайные из блока", callback_data="mode:random")],
        [InlineKeyboardButton("📚 По теме блока", callback_data="mode:choose_topic")],
        [InlineKeyboardButton("⬅️ Назад к блокам", callback_data="to_blocks")],
        [InlineKeyboardButton("🔙 К выбору режима", callback_data=CallbackData.TEST_TO_MENU)]
    ])

def get_topics_keyboard(block_name: str, topics: List[str]) -> Optional[InlineKeyboardMarkup]:
    """Создает клавиатуру для выбора темы."""
    if not topics:
        return None
    
    buttons = []
    
    # Создаем кнопки для тем
    for topic in topics:
        topic_display = TOPIC_NAMES.get(topic, topic)
        # Ограничиваем длину текста кнопки
        if len(topic_display) > 35:
            topic_display = topic_display[:32] + "..."
        
        buttons.append([InlineKeyboardButton(
            topic_display, 
            callback_data=f"topic:{topic}"
        )])
    
    # Кнопки навигации
    buttons.append([InlineKeyboardButton("⬅️ Назад к режиму", callback_data="to_mode")])
    buttons.append([InlineKeyboardButton("🔙 К выбору режима", callback_data=CallbackData.TEST_TO_MENU)])
    
    return InlineKeyboardMarkup(buttons)

def get_exam_number_keyboard(numbers: List[int]) -> Optional[InlineKeyboardMarkup]:
    """Создает клавиатуру для выбора номера задания ЕГЭ."""
    if not numbers:
        return None
    
    # Фильтруем только корректные номера (1-27 для ЕГЭ по обществознанию)
    valid_numbers = [n for n in numbers if 1 <= n <= 27]
    
    if not valid_numbers:
        return None
    
    buttons = []
    row = []
    
    for i, number in enumerate(sorted(valid_numbers), 1):
        button = InlineKeyboardButton(
            text=str(number),
            callback_data=f"exam_number:select:{number}"
        )
        row.append(button)
        
        # По 6 кнопок в ряд
        if i % 6 == 0:
            buttons.append(row)
            row = []
    
    # Добавляем оставшиеся кнопки
    if row:
        buttons.append(row)
    
    # Кнопка назад
    buttons.append([InlineKeyboardButton(
        "⬅️ Назад",
        callback_data="exam_number:back_to_initial"
    )])
    
    return InlineKeyboardMarkup(buttons)

def get_after_answer_keyboard(last_mode: str = "random") -> InlineKeyboardMarkup:
    """Клавиатура после проверки ответа."""
    
    if last_mode == "topic":
        main_button = InlineKeyboardButton("➡️ Ещё вопрос по теме", callback_data=CallbackData.NEXT_TOPIC)
    elif last_mode == "exam_num":
        main_button = InlineKeyboardButton("➡️ Следующий номер", callback_data=CallbackData.NEXT_RANDOM)
    else:  # random
        main_button = InlineKeyboardButton("➡️ Ещё случайный", callback_data=CallbackData.NEXT_RANDOM)

    return InlineKeyboardMarkup([
        [main_button],
        [InlineKeyboardButton("🔄 Сменить тему / режим", callback_data=CallbackData.CHANGE_TOPIC)],
        [InlineKeyboardButton("🏠 Главное меню", callback_data=CallbackData.TO_MAIN_MENU)],
    ])

def get_mistakes_nav_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Следующая ошибка", callback_data=CallbackData.NEXT_MISTAKE)],
        [InlineKeyboardButton("⏩ Пропустить", callback_data=CallbackData.SKIP_MISTAKE)],
        [InlineKeyboardButton("🚪 Закончить разбор", callback_data=CallbackData.EXIT_MISTAKES)],
        [InlineKeyboardButton("🏠 Главное меню", callback_data=CallbackData.TO_MAIN_MENU)],
    ])

def get_next_action_keyboard(last_mode: str, has_explanation: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура действий после ответа (ОСНОВНАЯ ВЕРСИЯ)."""
    keyboard = []
    
    # Первый ряд - основные действия
    first_row = []
    
    # Кнопка "Следующий вопрос"
    if last_mode == "topic":
        next_text = "➡️ Следующий вопрос по теме"
    elif last_mode == "exam_num":
        next_text = "➡️ Следующий вопрос №"
    elif last_mode == "block":
        next_text = "➡️ Следующий из блока"
    elif last_mode == "mistakes":
        next_text = "➡️ Следующая ошибка"
    else:  # random_all
        next_text = "➡️ Следующий случайный"
    
    first_row.append(
        InlineKeyboardButton(
            next_text,
            callback_data=CallbackData.TEST_NEXT_CONTINUE,
        )
    )
    
    # Добавляем кнопку пояснения если есть (во второй ряд для лучшего размещения)
    keyboard.append(first_row)
    
    # Второй ряд - пояснение (если есть)
    if has_explanation:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "💡 Показать пояснение",
                    callback_data=CallbackData.TEST_NEXT_SHOW_EXPLANATION,
                )
            ]
        )
    
    # Третий ряд - навигация
    nav_row = []
    
    if last_mode in ["topic", "exam_num", "block"]:
        nav_row.append(
            InlineKeyboardButton(
                "🔄 Сменить тему",
                callback_data=CallbackData.TEST_NEXT_CHANGE_TOPIC,
            )
        )
    else:
        nav_row.append(
            InlineKeyboardButton(
                "🔄 Сменить режим",
                callback_data=CallbackData.TEST_NEXT_CHANGE_TOPIC,
            )
        )
    
    keyboard.append(nav_row)
    
    # Четвертый ряд - главное меню
    keyboard.append(
        [
            InlineKeyboardButton(
                "🏠 Главное меню",
                callback_data=CallbackData.TEST_NEXT_CHANGE_BLOCK,
            )
        ]
    )
    
    return InlineKeyboardMarkup(keyboard)

def get_subscription_keyboard(channel: str) -> InlineKeyboardMarkup:
    """Клавиатура для проверки подписки."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подписаться", url=f"https://t.me/{channel.lstrip('@')}")],
        [InlineKeyboardButton("🔄 Я подписался", callback_data="check_subscription")]
    ])

def get_error_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для ошибок."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Попробовать снова", callback_data=CallbackData.TEST_TO_MENU)],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])

def get_stats_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для команды статистики."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Детальный отчет", callback_data="detailed_report"),
            InlineKeyboardButton("📤 Экспорт CSV", callback_data="export_csv")
        ],
        [InlineKeyboardButton("🔧 Работать над ошибками", callback_data="work_mistakes")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])

# Заменить функцию get_mistakes_nav_keyboard:
def get_mistakes_nav_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура навигации по ошибкам."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➡️ Следующая ошибка",
                    callback_data=CallbackData.TEST_NEXT_CONTINUE,
                )
            ],
            [
                InlineKeyboardButton(
                    "⏩ Пропустить",
                    callback_data=CallbackData.TEST_MISTAKE_SKIP,
                )
            ],
            [
                InlineKeyboardButton(
                    "🚪 Закончить разбор",
                    callback_data=CallbackData.TEST_MISTAKE_FINISH,
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Главное меню",
                    callback_data=CallbackData.TEST_NEXT_CHANGE_BLOCK,
                )
            ],
        ]
    )
