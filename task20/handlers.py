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
    
    data_file = os.path.join(os.path.dirname(__file__), "task20_topics.json")
    
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        
        # Преобразуем данные: собираем все темы в единый список
        all_topics = []
        topic_by_id = {}
        topics_by_block = {}
        
        for block_name, block in raw.get("blocks", {}).items():
            topics_by_block[block_name] = []
            for topic in block.get("topics", []):
                topic["block"] = block_name
                all_topics.append(topic)
                topic_by_id[topic["id"]] = topic
                topics_by_block[block_name].append(topic)
        
        raw["topics"] = all_topics
        raw["topic_by_id"] = topic_by_id
        raw["topics_by_block"] = topics_by_block
        
        task20_data = raw
        
        logger.info(f"Loaded {len(all_topics)} topics for task20")
    except Exception as e:
        logger.error(f"Failed to load task20 data: {e}")
        task20_data = {"topics": [], "blocks": {}, "topics_by_block": {}}

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

async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики - выбор способа тренировки."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "💪 <b>Режим практики</b>\n\n"
        "Выберите способ тренировки:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Выбрать блок тем", callback_data="t20_select_block")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t20_random_all")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим теории и советов."""
    query = update.callback_query
    await query.answer()
    
    text = """📚 <b>Теория по заданию 20</b>

<b>Что требуется в задании 20?</b>
Сформулировать суждения (аргументы) абстрактного характера с элементами обобщения.

<b>Ключевые отличия от задания 19:</b>
• Задание 19 - конкретные примеры
• Задание 20 - абстрактные суждения

<b>Критерии оценивания:</b>
• 3 балла - приведены 3 суждения правильного типа
• 2 балла - приведено 2 суждения
• 1 балл - приведено 1 суждение
• 0 баллов - суждения неверного типа или отсутствуют

<b>Важно:</b> Если наряду с требуемыми суждениями приведено 2 или более дополнительных суждения с ошибками, ответ оценивается в 0 баллов!

Выберите раздел для изучения:"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Как писать суждения", callback_data="t20_how_to_write")],
        [InlineKeyboardButton("✅ Правильные примеры", callback_data="t20_good_examples")],
        [InlineKeyboardButton("❌ Типичные ошибки", callback_data="t20_common_mistakes")],
        [InlineKeyboardButton("🔤 Полезные конструкции", callback_data="t20_useful_phrases")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def how_to_write(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Как писать суждения."""
    query = update.callback_query
    await query.answer()
    
    text = """📝 <b>Как писать суждения для задания 20</b>

<b>1. Структура суждения:</b>
• Начните с обобщающего тезиса
• Раскройте причинно-следственную связь
• Завершите выводом или следствием

<b>2. Используйте абстрактные понятия:</b>
• "Экономические субъекты" вместо "компания Apple"
• "Развитые страны" вместо "США и Германия"
• "Современные технологии" вместо "iPhone 15"

<b>3. Применяйте обобщающие слова:</b>
• Процессы: способствует, приводит к, порождает
• Влияние: определяет, формирует, трансформирует
• Связи: обусловливает, детерминирует, коррелирует

<b>4. Избегайте:</b>
• Конкретных дат и чисел
• Названий организаций и стран
• Имён конкретных людей
• Описания единичных событий

<b>Пример правильного суждения:</b>
<i>"Развитие информационных технологий способствует глобализации экономических процессов, позволяя хозяйствующим субъектам осуществлять деятельность вне зависимости от географических границ."</i>"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE
    
async def good_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Примеры правильных суждений."""
    query = update.callback_query
    await query.answer()
    
    text = """✅ <b>Примеры правильных суждений</b>

<b>Тема: Роль образования</b>

<u>Правильно:</u>
<i>"Система образования формирует человеческий капитал общества, обеспечивая передачу накопленных знаний и навыков новым поколениям, что является необходимым условием социально-экономического развития."</i>

<b>Почему правильно:</b>
• Абстрактные понятия (система, капитал, поколения)
• Причинно-следственная связь
• Обобщающие слова (формирует, обеспечивая)

<b>Тема: Влияние конкуренции</b>

<u>Правильно:</u>
<i>"Конкурентная среда стимулирует предпринимателей к постоянному совершенствованию производственных процессов, что способствует повышению эффективности экономики в целом."</i>

<b>Почему правильно:</b>
• Нет конкретных примеров
• Есть обобщение (экономика в целом)
• Логическая связь между частями

<b>Тема: СМИ и общество</b>

<u>Правильно:</u>
<i>"Средства массовой информации выполняют функцию социального контроля, привлекая внимание общественности к нарушениям норм и злоупотреблениям, что способствует поддержанию социального порядка."</i>

<b>Почему правильно:</b>
• Указана функция, а не конкретный случай
• Абстрактное описание механизма
• Вывод о влиянии на общество"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def common_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Типичные ошибки."""
    query = update.callback_query
    await query.answer()
    
    text = """❌ <b>Типичные ошибки в задании 20</b>

<b>Ошибка 1: Конкретные примеры вместо суждений</b>

<u>Неправильно:</u>
<i>"В 2020 году компания Tesla увеличила производство электромобилей на 50%, что показывает влияние инноваций на развитие промышленности."</i>

<b>Почему неправильно:</b>
• Конкретная дата (2020 год)
• Название компании (Tesla)
• Конкретные цифры (50%)

<u>Как исправить:</u>
<i>"Внедрение инновационных технологий способствует росту производительности в промышленном секторе и модернизации производственных процессов."</i>

<b>Ошибка 2: Простое перечисление фактов</b>

<u>Неправильно:</u>
<i>"Глобализация есть. Она влияет на культуру. Культуры меняются."</i>

<b>Почему неправильно:</b>
• Нет развёрнутого суждения
• Отсутствуют причинно-следственные связи
• Слишком простые предложения

<b>Ошибка 3: Бытовые рассуждения</b>

<u>Неправильно:</u>
<i>"Все знают, что образование важно для человека, потому что без него никуда."</i>

<b>Почему неправильно:</b>
• Разговорный стиль
• Нет теоретического обоснования
• Отсутствует научная терминология

<b>Помните:</b> Суждение должно звучать как фрагмент научной статьи, а не как пример из жизни!"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def useful_phrases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полезные конструкции."""
    query = update.callback_query
    await query.answer()
    
    text = """🔤 <b>Полезные конструкции для задания 20</b>

<b>Для выражения влияния:</b>
• способствует развитию...
• приводит к формированию...
• обусловливает появление...
• детерминирует процессы...
• оказывает воздействие на...

<b>Для обобщения:</b>
• в современном обществе...
• в условиях рыночной экономики...
• в процессе социализации...
• в системе общественных отношений...
• в структуре социальных институтов...

<b>Для причинно-следственных связей:</b>
• вследствие чего...
• что позволяет...
• благодаря чему...
• в результате чего...
• это обеспечивает...

<b>Для характеристики процессов:</b>
• трансформация... происходит...
• модернизация... выражается в...
• эволюция... проявляется через...
• динамика... определяется...

<b>Для указания функций:</b>
• выполняет функцию...
• реализует задачу...
• обеспечивает условия для...
• создаёт предпосылки...

<b>Шаблон суждения:</b>
[Субъект] + [действие с обобщающим словом] + [объект], + [связка] + [следствие/результат]

<b>Пример:</b>
<i>"Социальные институты</i> (субъект) <i>формируют</i> (действие) <i>нормативную основу общества</i> (объект), <i>что обеспечивает</i> (связка) <i>стабильность социальных взаимодействий</i> (результат)."
"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def handle_theory_sections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общий обработчик для разделов теории."""
    query = update.callback_query
    
    if query.data == "t20_how_to_write":
        return await how_to_write(update, context)
    elif query.data == "t20_good_examples":
        return await good_examples(update, context)
    elif query.data == "t20_common_mistakes":
        return await common_mistakes(update, context)
    elif query.data == "t20_useful_phrases":
        return await useful_phrases(update, context)
    
    return states.CHOOSING_MODE

async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Банк суждений - начальное меню."""
    query = update.callback_query
    await query.answer()
    
    context.user_data['bank_current_idx'] = 0
    
    text = (
        "🏦 <b>Банк суждений</b>\n\n"
        "Здесь собраны эталонные суждения по всем темам задания 20.\n\n"
        "Изучайте примеры, чтобы понять:\n"
        "• Как формулировать абстрактные суждения\n"
        "• Какие обобщающие конструкции использовать\n"
        "• Как избегать конкретных примеров\n\n"
        "Выберите способ просмотра:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Просмотр по порядку", callback_data="t20_bank_nav:0")],
        [InlineKeyboardButton("🔍 Поиск темы", callback_data="t20_bank_search")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса пользователя."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task20_results', [])
    
    if not results:
        await query.edit_message_text(
            "📊 <b>Ваш прогресс</b>\n\n"
            "Вы еще не выполнили ни одного задания.\n"
            "Начните с режима практики!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💪 Начать практику", callback_data="t20_practice"),
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
            ]]),
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_MODE
    
    # Подсчет статистики
    total_attempts = len(results)
    total_score = sum(r['score'] for r in results)
    max_possible_score = total_attempts * 3
    average_score = total_score / total_attempts
    
    # Статистика по блокам
    blocks_stats = {}
    for result in results:
        block = result['block']
        if block not in blocks_stats:
            blocks_stats[block] = {'attempts': 0, 'total_score': 0}
        blocks_stats[block]['attempts'] += 1
        blocks_stats[block]['total_score'] += result['score']
    
    text = f"""📊 <b>Ваш прогресс</b>

<b>Общая статистика:</b>
• Выполнено заданий: {total_attempts}
• Общий балл: {total_score}/{max_possible_score}
• Средний балл: {average_score:.1f}/3

<b>По блокам:</b>
"""
    
    for block, stats in blocks_stats.items():
        avg = stats['total_score'] / stats['attempts']
        text += f"\n<b>{block}:</b>\n"
        text += f"  • Попыток: {stats['attempts']}\n"
        text += f"  • Средний балл: {avg:.1f}/3\n"
    
    # Последние результаты
    text += "\n<b>Последние результаты:</b>\n"
    for result in results[-3:]:
        text += f"• {result['topic_title']}: {result['score']}/3\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Подробная статистика", callback_data="t20_detailed_progress")],
        [InlineKeyboardButton("📤 Экспорт результатов", callback_data="t20_export")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки проверки."""
    query = update.callback_query
    await query.answer()
    
    text = """⚙️ <b>Настройки проверки</b>

<b>Текущий режим:</b> Базовая проверка

В будущих версиях здесь можно будет настроить:
• Уровень строгости AI-проверки
• Детальность обратной связи
• Автоматическое выявление ошибок

<b>Доступные настройки:</b>"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Сбросить прогресс", callback_data="t20_reset_progress")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс прогресса - подтверждение."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "⚠️ <b>Подтверждение сброса</b>\n\n"
        "Вы уверены, что хотите сбросить весь прогресс по заданию 20?\n"
        "Это действие нельзя отменить!",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да, сбросить", callback_data="t20_confirm_reset"),
                InlineKeyboardButton("❌ Отмена", callback_data="t20_settings")
            ]
        ]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def confirm_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса прогресса."""
    query = update.callback_query
    await query.answer()
    
    # Сбрасываем результаты
    context.user_data['task20_results'] = []
    
    await query.answer("✅ Прогресс сброшен", show_alert=True)
    return await settings_mode(update, context)


async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 20."""
    query = update.callback_query
    await query.answer()
    
    # Очищаем временные данные
    keys_to_clear = ['current_topic', 'current_block', 'bank_current_idx', 'waiting_for_bank_search']
    for key in keys_to_clear:
        context.user_data.pop(key, None)
    
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

async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем."""
    query = update.callback_query
    await query.answer()
    
    blocks = list(task20_data.get("blocks", {}).keys())
    
    if not blocks:
        await query.edit_message_text(
            "❌ Блоки тем не найдены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    text = "📚 <b>Выберите блок тем:</b>"
    
    kb_buttons = []
    for block in blocks:
        topics_count = len(task20_data["topics_by_block"].get(block, []))
        kb_buttons.append([
            InlineKeyboardButton(
                f"{block} ({topics_count} тем)",
                callback_data=f"t20_block:{block}"
            )
        ])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_BLOCK

def _build_topic_message(topic: Dict) -> str:
    """Формирует текст сообщения с заданием по теме."""
    return (
        "📝 <b>Задание 20</b>\n\n"
        f"<b>Тема:</b> {topic['title']}\n"
        f"<b>Блок:</b> {topic['block']}\n\n"
        f"<b>Задание:</b> {topic['task_text']}\n\n"
        "<b>Требования:</b>\n"
        "• Приведите три суждения\n"
        "• Каждое суждение должно быть абстрактным\n"
        "• НЕ используйте конкретные примеры\n"
        "• Используйте обобщающие конструкции\n\n"
        "💡 <i>Отправьте ваш ответ одним сообщением</i>"
    )

async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после получения результата."""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split("_")[1]
    
    if action == "retry":
        # Повторить ту же тему
        topic = context.user_data.get('current_topic')
        if topic:
            text = _build_topic_message(topic)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="t20_menu")]
            ])
            await query.edit_message_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            return states.ANSWERING
    
    elif action == "new":
        # Вернуться к выбору темы
        return await practice_mode(update, context)
    
    return states.CHOOSING_MODE

async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбранного блока."""
    query = update.callback_query
    await query.answer()
    
    block_name = query.data.split(":", 1)[1]
    context.user_data['current_block'] = block_name
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    
    text = f"📚 <b>Блок: {block_name}</b>\n\n"
    text += f"Доступно тем: {len(topics)}\n\n"
    text += "Выберите действие:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Список тем", callback_data="t20_list_topics")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t20_random_block")],
        [InlineKeyboardButton("⬅️ К блокам", callback_data="t20_select_block")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка тем в блоке с пагинацией."""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем номер страницы из callback_data
    parts = query.data.split(":page:")
    page = int(parts[1]) if len(parts) > 1 else 0
    
    block_name = context.user_data.get('current_block')
    if not block_name:
        await query.edit_message_text(
            "❌ Блок не выбран",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_select_block")
            ]])
        )
        return states.CHOOSING_MODE
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    
    # Пагинация: 5 тем на страницу
    topics_per_page = 5
    total_pages = (len(topics) + topics_per_page - 1) // topics_per_page
    start_idx = page * topics_per_page
    end_idx = min(start_idx + topics_per_page, len(topics))
    
    text = f"📚 <b>{block_name}</b>\n"
    text += f"Страница {page + 1} из {total_pages}\n\n"
    text += "Выберите тему:\n"
    
    kb_buttons = []
    
    # Кнопки с темами
    for topic in topics[start_idx:end_idx]:
        kb_buttons.append([
            InlineKeyboardButton(
                f"{topic['id']}. {topic['title']}",
                callback_data=f"t20_topic:{topic['id']}"
            )
        ])
    
    # Навигация по страницам
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t20_list_topics:page:{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t20_list_topics:page:{page+1}"))
    
    if nav_buttons:
        kb_buttons.append(nav_buttons)
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"t20_block:{block_name}")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_TOPIC

async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы из всех."""
    query = update.callback_query
    await query.answer()
    
    import random
    
    topics = task20_data.get("topics", [])
    if not topics:
        await query.edit_message_text(
            "❌ Темы не найдены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    topic = random.choice(topics)
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t20_practice")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING

async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы из блока."""
    query = update.callback_query
    await query.answer()
    
    import random
    
    block_name = context.user_data.get('current_block')
    if not block_name:
        await query.edit_message_text(
            "❌ Блок не выбран",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_select_block")
            ]])
        )
        return states.CHOOSING_MODE
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    if not topics:
        await query.edit_message_text(
            "❌ В блоке нет тем",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data=f"t20_block:{block_name}")
            ]])
        )
        return states.CHOOSING_MODE
    
    topic = random.choice(topics)
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=f"t20_block:{block_name}")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING


async def bank_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку суждений."""
    query = update.callback_query
    await query.answer()
    
    topic_idx = int(query.data.split(":")[1])
    topics = task20_data.get('topics', [])
    
    if not topics or topic_idx >= len(topics):
        await query.edit_message_text("❌ Тема не найдена")
        return states.CHOOSING_MODE
    
    topic = topics[topic_idx]
    context.user_data['bank_current_idx'] = topic_idx
    
    text = f"""🏦 <b>Банк суждений</b>

<b>Тема:</b> {topic['title']}
<b>Блок:</b> {topic['block']}

<b>Задание:</b>
{topic['task_text']}

<b>Эталонные суждения:</b>

"""
    
    for i, example in enumerate(topic.get('example_arguments', []), 1):
        text += f"<b>{i}. {example['type']}</b>\n"
        text += f"<i>{example['argument']}</i>\n\n"
    
    text += "💡 <b>Обратите внимание:</b>\n"
    text += "• Суждения носят абстрактный характер\n"
    text += "• Используются обобщающие слова\n"
    text += "• Нет конкретных примеров и дат"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t20_bank_nav:{topic_idx-1}"))
    
    nav_row.append(InlineKeyboardButton(f"{topic_idx+1}/{len(topics)}", callback_data="noop"))
    
    if topic_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t20_bank_nav:{topic_idx+1}"))
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("🔍 Поиск темы", callback_data="t20_bank_search")])
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск темы в банке суждений."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔍 <b>Поиск в банке суждений</b>\n\n"
        "Отправьте название темы или ключевые слова для поиска:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="t20_examples")
        ]]),
        parse_mode=ParseMode.HTML
    )
    
    context.user_data['waiting_for_bank_search'] = True
    return states.SEARCHING

async def set_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройка строгости (заглушка)."""
    query = update.callback_query
    await query.answer("Функция будет доступна после подключения AI-проверки", show_alert=True)
    return states.CHOOSING_MODE

async def handle_settings_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик действий в настройках."""
    query = update.callback_query
    
    if query.data == "t20_reset_progress":
        return await reset_progress(update, context)
    elif query.data == "t20_confirm_reset":
        return await confirm_reset(update, context)
    
    return states.CHOOSING_MODE

async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика - заглушка."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📈 <b>Детальная статистика</b>\n\n"
        "Функция в разработке...",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")
        ]]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def export_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт результатов - заглушка."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📤 <b>Экспорт результатов</b>\n\n"
        "Функция в разработке...",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")
        ]]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def choose_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы и показ задания."""
    query = update.callback_query
    await query.answer()
    
    topic_id = int(query.data.split(":")[1])
    topic = task20_data["topic_by_id"].get(topic_id)
    
    if not topic:
        await query.edit_message_text(
            "❌ Тема не найдена",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_select_block")
            ]])
        )
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t20_select_block")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя."""
    user_answer = update.message.text
    topic = context.user_data.get('current_topic')
    
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 К заданиям", callback_data="t20_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Сохраняем ответ
    if 'task20_results' not in context.user_data:
        context.user_data['task20_results'] = []
    
    # Простая проверка на количество суждений (по количеству абзацев/предложений)
    arguments = [arg.strip() for arg in user_answer.split('\n') if arg.strip()]
    
    # Базовая оценка
    score = 0
    feedback_points = []
    
    # Проверяем количество аргументов
    if len(arguments) >= 3:
        score = 3
        feedback_points.append("✅ Приведено достаточное количество суждений")
    elif len(arguments) == 2:
        score = 2
        feedback_points.append("⚠️ Приведено только 2 суждения из 3 требуемых")
    elif len(arguments) == 1:
        score = 1
        feedback_points.append("❌ Приведено только 1 суждение из 3 требуемых")
    else:
        score = 0
        feedback_points.append("❌ Суждения не обнаружены")
    
    # Проверяем на наличие конкретных примеров (простая эвристика)
    concrete_indicators = [
        'например', 'в 20', 'году', 'компания', 'страна', 
        'россия', 'сша', 'китай', 'франция', 'германия',
        'apple', 'google', 'microsoft', 'января', 'февраля',
        'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
        'сентября', 'октября', 'ноября', 'декабря'
    ]
    
    has_concrete = any(indicator in user_answer.lower() for indicator in concrete_indicators)
    if has_concrete and score > 0:
        score = max(0, score - 1)
        feedback_points.append("⚠️ Обнаружены конкретные примеры (даты, названия компаний/стран)")
    
    # Проверяем наличие обобщающих конструкций
    generalizing_words = [
        'способствует', 'приводит к', 'влияет на', 'обеспечивает',
        'позволяет', 'создает', 'формирует', 'развивает', 'определяет',
        'препятствует', 'ограничивает', 'снижает', 'повышает',
        'улучшает', 'ухудшает', 'стимулирует', 'порождает'
    ]
    
    has_generalizing = any(word in user_answer.lower() for word in generalizing_words)
    if has_generalizing:
        feedback_points.append("✅ Использованы обобщающие конструкции")
    else:
        feedback_points.append("💡 Рекомендуется использовать больше обобщающих слов")
    
    # Сохраняем результат
    result = {
        'topic_id': topic['id'],
        'topic_title': topic['title'],
        'block': topic['block'],
        'answer': user_answer,
        'score': score,
        'max_score': 3,
        'timestamp': datetime.now().isoformat(),
        'arguments_count': len(arguments)
    }
    
    context.user_data['task20_results'].append(result)
    
    # Формируем отзыв
    feedback = f"📊 <b>Результаты проверки</b>\n\n"
    feedback += f"<b>Тема:</b> {topic['title']}\n"
    feedback += f"<b>Оценка:</b> {score}/3 баллов\n\n"
    
    feedback += "<b>Анализ ответа:</b>\n"
    for point in feedback_points:
        feedback += f"{point}\n"
    
    feedback += "\n<b>Эталонные суждения по теме:</b>\n\n"
    for i, example in enumerate(topic.get('example_arguments', [])[:3], 1):
        feedback += f"{i}. <i>{example['argument']}</i>\n\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Попробовать снова", callback_data="t20_retry")],
        [InlineKeyboardButton("📝 Новая тема", callback_data="t20_new_topic")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t20_progress")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")]
    ])
    
    await update.message.reply_text(
        feedback,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_FEEDBACK

async def handle_bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поискового запроса в банке суждений."""
    if not context.user_data.get('waiting_for_bank_search'):
        return
    
    search_query = update.message.text.lower()
    context.user_data['waiting_for_bank_search'] = False
    
    # Ищем подходящие темы
    matching_topics = []
    for idx, topic in enumerate(task20_data.get('topics', [])):
        if (search_query in topic['title'].lower() or 
            search_query in topic.get('task_text', '').lower() or
            search_query in topic.get('block', '').lower()):
            matching_topics.append((idx, topic))
    
    if not matching_topics:
        await update.message.reply_text(
            "❌ Темы не найдены. Попробуйте другой запрос.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Искать снова", callback_data="t20_bank_search"),
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_examples")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем результаты поиска
    text = f"✅ Найдено тем: {len(matching_topics)}\n\n"
    
    kb_buttons = []
    for idx, (topic_idx, topic) in enumerate(matching_topics[:10]):  # Показываем до 10 результатов
        kb_buttons.append([
            InlineKeyboardButton(
                f"{topic['title']}",
                callback_data=f"t20_bank_nav:{topic_idx}"
            )
        ])
    
    if len(matching_topics) > 10:
        text += f"<i>Показаны первые 10 из {len(matching_topics)} результатов</i>"
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_examples")])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 В меню задания 20", callback_data="t20_menu"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
        ]])
    )
    return ConversationHandler.END
