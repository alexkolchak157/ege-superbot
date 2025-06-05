import math
import html
from typing import List, Tuple, Optional, Set
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру главного меню task24."""
    keyboard = [
        [InlineKeyboardButton("💪 Тренироваться", callback_data="start_train")],
        [InlineKeyboardButton("👀 Посмотреть эталоны", callback_data="start_show")],
        [InlineKeyboardButton("🎯 Режим экзамена", callback_data="start_exam")],
        [InlineKeyboardButton("🔍 Поиск темы", callback_data="search_topics")],
        [InlineKeyboardButton("📜 Список всех тем", callback_data="show_list")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="show_progress")],
        [InlineKeyboardButton("📋 Критерии оценки", callback_data="show_criteria")],
        [InlineKeyboardButton("❓ Помощь", callback_data="show_help")],
        [InlineKeyboardButton("🔄 Сбросить прогресс", callback_data="reset_progress")],
        [InlineKeyboardButton("📤 Экспорт прогресса", callback_data="export_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_progress_keyboard(practiced_indices: Set[int], total: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру с детальной статистикой прогресса."""
    completed = len(practiced_indices)
    progress = int(completed / total * 100) if total > 0 else 0
    
    # Визуальная шкала прогресса
    filled = "█" * (progress // 10)
    empty = "░" * (10 - progress // 10)
    progress_bar = f"{filled}{empty}"
    
    keyboard = [
        [InlineKeyboardButton(
            f"📊 Прогресс: {progress_bar} {progress}%",
            callback_data="show_detailed_progress"
        )],
        [
            InlineKeyboardButton(
                f"✅ Пройдено: {completed}",
                callback_data="show_completed"
            ),
            InlineKeyboardButton(
                f"📝 Осталось: {total - completed}",
                callback_data="show_remaining"
            )
        ],
        [InlineKeyboardButton("📤 Экспорт прогресса", callback_data="export_progress")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="start_button")]
    ]
    
    return InlineKeyboardMarkup(keyboard)

def build_initial_choice_keyboard(mode: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для начального выбора способа поиска темы."""
    keyboard = [
        [InlineKeyboardButton("📚 По блокам", callback_data=f"nav:choose_block:{mode}")],
        [InlineKeyboardButton("🗂️ Все темы списком", callback_data=f"nav:show_all:{mode}")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data=f"nav:random:{mode}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="start_button")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_block_selection_keyboard(mode: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора блока тем."""
    # Предопределенные блоки (должны соответствовать данным в JSON)
    THEORY_BLOCKS = [
        "Человек и общество", 
        "Экономика", 
        "Социальные отношения",
        "Политика", 
        "Право"
    ]
    
    keyboard = []
    for block_name in THEORY_BLOCKS:
        keyboard.append([InlineKeyboardButton(
            f"📁 {block_name}", 
            callback_data=f"nav:select_block:{mode}:{block_name}"
        )])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"nav:back_to_main:{mode}")])
    return InlineKeyboardMarkup(keyboard)

def build_topic_page_keyboard(
    mode: str,
    page: int,
    bot_data,
    practiced_indices: Set[int],
    block_name: Optional[str] = None
) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    """Создает текст и клавиатуру для указанной страницы тем."""
    ITEMS_PER_PAGE = 8  # Уменьшено для удобства
    
    # Получаем список тем
    if block_name:
        topic_list = bot_data.topics_by_block.get(block_name, [])
        list_source = "block"
    else:
        topic_list = bot_data.get_all_topics_list()
        list_source = "all"
    
    if not topic_list:
        title_suffix = f" (блок: {html.escape(block_name)})" if block_name else " (все темы)"
        return f"❌ Темы{title_suffix} не найдены.", None
    
    # Пагинация
    total_items = len(topic_list)
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    
    start_index = page * ITEMS_PER_PAGE
    end_index = min(start_index + ITEMS_PER_PAGE, total_items)
    page_items = topic_list[start_index:end_index]
    
    # Формируем текст
    action_text = "тренировки" if mode == "train" else "просмотра эталона"
    title_suffix = f"\n📁 Блок: <b>{html.escape(block_name)}</b>" if block_name else ""
    
    message_text = f"📋 <b>Выберите тему для {action_text}</b>{title_suffix}\n\n"
    
    # Добавляем статистику
    completed = len([idx for idx, _ in topic_list if idx in practiced_indices])
    total = len(topic_list)
    progress = int(completed / total * 100) if total > 0 else 0
    message_text += f"📊 Прогресс: {completed}/{total} ({progress}%)\n"
    message_text += "━" * 25 + "\n\n"
    
    # Создаем кнопки для тем
    keyboard_rows = []
    for index, topic_name in page_items:
        # Сокращаем длинные названия
        display_name = topic_name if len(topic_name) < 45 else topic_name[:42] + "..."
        marker = "✅" if index in practiced_indices else "📄"
        
        keyboard_rows.append([InlineKeyboardButton(
            f"{marker} {display_name}", 
            callback_data=f"topic:{mode}:{index}"
        )])
    
    # Навигация по страницам
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            "⬅️", 
            callback_data=f"nav:{list_source}:{mode}:{page-1}" + (f":{block_name}" if block_name else "")
        ))
    
    nav_buttons.append(InlineKeyboardButton(
        f"{page + 1}/{total_pages}", 
        callback_data="noop"
    ))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            "➡️", 
            callback_data=f"nav:{list_source}:{mode}:{page+1}" + (f":{block_name}" if block_name else "")
        ))
    
    if nav_buttons and len(nav_buttons) > 1:
        keyboard_rows.append(nav_buttons)
    
    # Кнопка назад
    if block_name:
        keyboard_rows.append([InlineKeyboardButton(
            "⬅️ К выбору блока", 
            callback_data=f"nav:choose_block:{mode}"
        )])
    else:
        keyboard_rows.append([InlineKeyboardButton(
            "⬅️ Назад", 
            callback_data=f"nav:back_to_main:{mode}"
        )])
    
    if not page_items:
        return f"На этой странице нет тем{title_suffix}.", InlineKeyboardMarkup(keyboard_rows[-1:])
    
    return message_text, InlineKeyboardMarkup(keyboard_rows)

def build_search_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для поиска."""
    keyboard = [
        [InlineKeyboardButton("❌ Отмена", callback_data="start_button")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_feedback_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру после проверки плана."""
    keyboard = [
        [
            InlineKeyboardButton("🔄 Ещё тема", callback_data="next_topic"),
            InlineKeyboardButton("📝 Меню планов", callback_data="back_main")
        ],
        [
            InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)