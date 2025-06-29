import math
import html
from typing import List, Tuple, Optional, Set
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.universal_ui import AdaptiveKeyboards

def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру главного меню task24."""
    keyboard = [
        [InlineKeyboardButton("💪 Тренироваться", callback_data="t24_train")],
        [InlineKeyboardButton("👀 Посмотреть эталоны", callback_data="t24_show")],
        [InlineKeyboardButton("🎯 Режим экзамена", callback_data="t24_exam")],
        [InlineKeyboardButton("🔍 Поиск темы", callback_data="t24_search")],
        [InlineKeyboardButton("📜 Список всех тем", callback_data="t24_show_list")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t24_progress")],
        [InlineKeyboardButton("📋 Критерии оценки", callback_data="t24_criteria")],
        [InlineKeyboardButton("❓ Помощь", callback_data="t24_help")],
        [InlineKeyboardButton("🔄 Сбросить прогресс", callback_data="t24_reset_progress")],
        [InlineKeyboardButton("📤 Экспорт прогресса", callback_data="export_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_progress_keyboard(practiced_indices: Set[int], total: int) -> InlineKeyboardMarkup:
    """Создает унифицированную клавиатуру с детальной статистикой прогресса."""
    completed = len(practiced_indices)
    progress = int(completed / total * 100) if total > 0 else 0
    
    # Визуальная шкала прогресса
    filled = "█" * (progress // 10)
    empty = "░" * (10 - progress // 10)
    progress_bar = f"{filled}{empty}"
    
    # Создаем кастомные кнопки для task24
    custom_buttons = [
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
        ]
    ]
    
    # Получаем базовую клавиатуру
    base_kb = AdaptiveKeyboards.create_progress_keyboard(
        has_detailed_stats=True,
        can_export=True,
        module_code="task24"
    )
    
    # Перестраиваем клавиатуру с новыми callback_data
    new_buttons = []
    
    # Добавляем кастомные кнопки вначале
    new_buttons.extend(custom_buttons)
    
    # Обрабатываем кнопки из базовой клавиатуры
    for row in base_kb.inline_keyboard:
        new_row = []
        for button in row:
            # Создаем новую кнопку с правильным callback_data
            if button.callback_data == "task24_detailed_progress":
                # Пропускаем, так как у нас уже есть кастомная кнопка детального прогресса
                continue
            elif button.callback_data == "task24_export":
                new_row.append(InlineKeyboardButton(button.text, callback_data="export_progress"))
            elif button.callback_data == "task24_menu":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_menu"))
            elif button.callback_data == "task24_reset_confirm":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_reset_progress"))
            elif button.callback_data == "task24_practice":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_train"))
            else:
                # Оставляем как есть
                new_row.append(InlineKeyboardButton(button.text, callback_data=button.callback_data))
        
        if new_row:  # Добавляем только непустые строки
            new_buttons.append(new_row)
    
    return InlineKeyboardMarkup(new_buttons)

def build_initial_choice_keyboard(mode: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для начального выбора способа поиска темы."""
    keyboard = [
        [InlineKeyboardButton("📚 По блокам", callback_data=f"t24_nav_choose_block:{mode}")],
        [InlineKeyboardButton("🗂️ Все темы списком", callback_data=f"t24_nav_show_all:{mode}")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data=f"t24_nav_random:{mode}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t24_menu")]
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
            callback_data=f"t24_nav_select_block:{mode}:{block_name}"
        )])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"t24_nav_back_to_main:{mode}")])
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
            callback_data=f"t24_topic_{mode}:{index}"
        )])
    
    # Навигация по страницам
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            "⬅️", 
            callback_data=f"t24_nav_{list_source}:{mode}:{page-1}" + (f":{block_name}" if block_name else "")
        ))
    
    nav_buttons.append(InlineKeyboardButton(
        f"{page + 1}/{total_pages}", 
        callback_data="noop"
    ))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            "➡️", 
            callback_data=f"t24_nav_{list_source}:{mode}:{page+1}" + (f":{block_name}" if block_name else "")
        ))
    
    if nav_buttons and len(nav_buttons) > 1:
        keyboard_rows.append(nav_buttons)
    
    # Кнопка назад
    if block_name:
        keyboard_rows.append([InlineKeyboardButton(
            "⬅️ К выбору блока", 
            callback_data=f"t24_nav_choose_block:{mode}"
        )])
    else:
        keyboard_rows.append([InlineKeyboardButton(
            "⬅️ Назад", 
            callback_data=f"t24_nav_back_to_main:{mode}"
        )])
    
    if not page_items:
        return f"На этой странице нет тем{title_suffix}.", InlineKeyboardMarkup(keyboard_rows[-1:])
    
    return message_text, InlineKeyboardMarkup(keyboard_rows)

def build_search_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для поиска."""
    keyboard = [
        [InlineKeyboardButton("❌ Отмена", callback_data="t24_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_feedback_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру после проверки плана."""
    # Использовать адаптивную клавиатуру
    # score нужно получить из контекста
    return AdaptiveKeyboards.create_result_keyboard(
        score=context.user_data.get('last_score', 0),
        max_score=4,
        module_code="task24"
    )