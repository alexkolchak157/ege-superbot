import math
import html
from typing import List, Tuple, Optional, Set, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.universal_ui import AdaptiveKeyboards

def build_main_menu_keyboard(user_stats: Optional[Dict[str, Any]] = None) -> InlineKeyboardMarkup:
    """Создает унифицированную клавиатуру главного меню task24."""
    
    # Если статистика не передана, создаем пустую
    if user_stats is None:
        user_stats = {
            'total_attempts': 0,
            'average_score': 0,
            'streak': 0,
            'weak_topics_count': 0,
            'progress_percent': 0
        }
    
    # Используем адаптивную клавиатуру
    base_kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="task24")
    
    # Создаем новую клавиатуру с правильными callback_data для task24
    new_buttons = []
    
    for row in base_kb.inline_keyboard:
        new_row = []
        for button in row:
            # Маппинг стандартных callback на специфичные для task24
            if button.callback_data == "task24_practice":
                new_row.append(InlineKeyboardButton("💪 Тренироваться", callback_data="t24_train"))
            elif button.callback_data == "task24_theory":
                new_row.append(InlineKeyboardButton("📋 Критерии оценки", callback_data="t24_criteria"))
            elif button.callback_data == "task24_examples":
                new_row.append(InlineKeyboardButton("👀 Посмотреть эталоны", callback_data="t24_show"))
            elif button.callback_data == "task24_progress":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_progress"))
            elif button.callback_data == "task24_settings":
                # Вместо настроек добавляем режим экзамена
                new_row.append(InlineKeyboardButton("🎯 Режим экзамена", callback_data="t24_exam"))
            elif button.callback_data == "task24_mistakes":
                # Пропускаем работу над ошибками, так как она не реализована в task24
                continue
            elif button.callback_data == "task24_achievements":
                # Пропускаем достижения
                continue
            elif button.callback_data == "task24_menu":
                # Это кнопка возврата в меню - не нужна в главном меню
                continue
            elif button.callback_data == "to_main_menu":
                new_row.append(button)  # Оставляем как есть
            else:
                new_row.append(button)
        
        if new_row:
            new_buttons.append(new_row)
    
    # Добавляем специфичные для task24 кнопки
    additional_buttons = [
        [InlineKeyboardButton("🔍 Поиск темы", callback_data="t24_search")],
        [InlineKeyboardButton("📜 Список всех тем", callback_data="t24_show_list")],
        [InlineKeyboardButton("❓ Помощь", callback_data="t24_help")]
    ]
    
    # Вставляем дополнительные кнопки перед последней строкой (где кнопка главного меню)
    if new_buttons and any("to_main_menu" in str(btn.callback_data) for btn in new_buttons[-1]):
        # Сохраняем последнюю строку
        last_row = new_buttons.pop()
        # Добавляем дополнительные кнопки
        new_buttons.extend(additional_buttons)
        # Добавляем кнопки управления прогрессом
        new_buttons.append([
            InlineKeyboardButton("🔄 Сбросить прогресс", callback_data="t24_reset_progress"),
            InlineKeyboardButton("📤 Экспорт прогресса", callback_data="export_progress")
        ])
        # Возвращаем последнюю строку
        new_buttons.append(last_row)
    else:
        new_buttons.extend(additional_buttons)
    
    return InlineKeyboardMarkup(new_buttons)

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
    
    # Вычисляем количество страниц
    total_pages = math.ceil(len(topic_list) / ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    
    # Получаем темы для текущей страницы
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_topics = topic_list[start_idx:end_idx]
    
    # Создаем текст с нумерацией
    title_suffix = f" (блок: {html.escape(block_name)})" if block_name else " (все темы)"
    message_text = f"<b>Список тем{title_suffix}</b>\n"
    message_text += f"Страница {page + 1} из {total_pages}\n\n"
    
    keyboard_rows = []
    
    # Добавляем темы на текущей странице
    for i, (topic_idx, topic_title) in enumerate(page_topics):
        display_number = start_idx + i + 1
        
        # Отмечаем пройденные темы
        if topic_idx in practiced_indices:
            mark = "✅"
        else:
            mark = "📄"
        
        # Текст для сообщения
        escaped_title = html.escape(topic_title[:100])
        if len(topic_title) > 100:
            escaped_title += "..."
        message_text += f"{display_number}. {mark} {escaped_title}\n"
        
        # Кнопка
        button_text = f"{mark} {topic_title[:50]}{'...' if len(topic_title) > 50 else ''}"
        callback_data = f"t24_topic_{mode}:{topic_idx}"
        
        keyboard_rows.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    # Навигация по страницам
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️", callback_data=f"t24_nav_page:{mode}:{list_source}:{page-1}:{block_name or ''}"))
    nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("▶️", callback_data=f"t24_nav_page:{mode}:{list_source}:{page+1}:{block_name or ''}"))
    
    if nav_row:
        keyboard_rows.append(nav_row)
    
    # Кнопка возврата
    keyboard_rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"t24_nav_back_to_main:{mode}")])
    
    # Ограничение: если кнопок слишком много, показываем только навигацию
    if len(keyboard_rows) > 12:
        return message_text + "\n<i>Используйте навигацию для выбора темы</i>", InlineKeyboardMarkup(keyboard_rows[-2:])
    
    return message_text, InlineKeyboardMarkup(keyboard_rows)

def build_search_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для поиска."""
    keyboard = [
        [InlineKeyboardButton("❌ Отмена", callback_data="t24_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_feedback_keyboard(score: int = 0, max_score: int = 4) -> InlineKeyboardMarkup:
    """Создает клавиатуру после проверки плана."""
    # Использовать адаптивную клавиатуру
    base_kb = AdaptiveKeyboards.create_result_keyboard(
        score=score,
        max_score=max_score,
        module_code="task24"
    )
    
    # Адаптируем callback_data для task24
    new_buttons = []
    
    for row in base_kb.inline_keyboard:
        new_row = []
        for button in row:
            # Маппинг callback_data
            if button.callback_data == "task24_retry":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_retry"))
            elif button.callback_data == "task24_new":
                new_row.append(InlineKeyboardButton(button.text, callback_data="next_topic"))
            elif button.callback_data == "task24_show_ideal":
                # Пропускаем, так как эталон уже показан
                continue
            elif button.callback_data == "task24_progress":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_progress"))
            elif button.callback_data == "task24_menu":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_menu"))
            elif button.callback_data == "task24_theory":
                new_row.append(InlineKeyboardButton("📋 Критерии", callback_data="t24_criteria"))
            elif button.callback_data == "task24_examples":
                new_row.append(InlineKeyboardButton("👀 Эталоны", callback_data="t24_show"))
            else:
                new_row.append(button)
        
        if new_row:
            new_buttons.append(new_row)
    
    return InlineKeyboardMarkup(new_buttons)