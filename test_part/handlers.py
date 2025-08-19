import logging
import random
from datetime import datetime
from core.state_validator import validate_state_transition, state_validator
import aiosqlite
import os
import csv
import io
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from core.plugin_loader import build_main_menu
from core import db, states
from core.admin_tools import admin_manager
from core.config import DATABASE_FILE, REQUIRED_CHANNEL
from core.ui_helpers import (create_visual_progress, get_motivational_message,
                             get_personalized_greeting,
                             show_streak_notification, show_thinking_animation)
from core.universal_ui import (AdaptiveKeyboards, MessageFormatter,
                               UniversalUIComponents)
from core.error_handler import safe_handler, auto_answer_callback
from core.utils import check_subscription, send_subscription_required
from . import keyboards, utils
from .loader import AVAILABLE_BLOCKS, QUESTIONS_DATA, QUESTIONS_DICT_FLAT

try:
    from .topic_data import TOPIC_NAMES
except ImportError:
    logger.warning("Не удалось импортировать TOPIC_NAMES из topic_data.py")
    TOPIC_NAMES = {}

try:
    from .cache import questions_cache
except ImportError:
    logging.warning("Модуль cache не найден, работаем без кеширования")
    questions_cache = None

logger = logging.getLogger(__name__)

# Добавить после импортов (новые функции):
def safe_cache_get_by_exam_num(exam_number):
    """Безопасное получение вопросов по номеру ЕГЭ."""
    if questions_cache:
        return questions_cache.get_by_exam_num(exam_number)
    
    # Fallback через QUESTIONS_DATA
    questions_with_num = []
    for block_data in QUESTIONS_DATA.values():
        for topic_questions in block_data.values():
            for question in topic_questions:
                if question.get("exam_number") == exam_number:
                    questions_with_num.append(question)
    return questions_with_num

def safe_cache_get_by_topic(topic):
    """Безопасное получение вопросов по теме."""
    if questions_cache:
        return questions_cache.get_by_topic(topic)
    
    # Fallback через QUESTIONS_DATA
    questions_in_topic = []
    for block_data in QUESTIONS_DATA.values():
        for topic_name, topic_questions in block_data.items():
            if topic_name == topic:
                questions_in_topic.extend(topic_questions)
    return questions_in_topic

def safe_cache_get_by_block(block):
    """Безопасное получение вопросов по блоку."""
    if questions_cache:
        return questions_cache.get_by_block(block)
    
    # Fallback через QUESTIONS_DATA
    questions_in_block = []
    for topic_questions in QUESTIONS_DATA.get(block, {}).values():
        questions_in_block.extend(topic_questions)
    return questions_in_block

def safe_cache_get_all_exam_numbers():
    """Безопасное получение всех номеров ЕГЭ."""
    if questions_cache:
        return questions_cache.get_all_exam_numbers()
    
    # Fallback через QUESTIONS_DATA
    exam_numbers = set()
    for block_data in QUESTIONS_DATA.values():
        for topic_questions in block_data.values():
            for question in topic_questions:
                exam_num = question.get("exam_number")
                if isinstance(exam_num, int):
                    exam_numbers.add(exam_num)
    return sorted(list(exam_numbers))

def init_data():
    """Инициализирует данные вопросов."""
    global QUESTIONS_DATA, AVAILABLE_BLOCKS, QUESTIONS_LIST
    try:
        from .loader import get_questions_data, get_questions_list_flat, get_available_blocks
        
        QUESTIONS_DATA = get_questions_data()
        if QUESTIONS_DATA:
            AVAILABLE_BLOCKS = get_available_blocks()
            QUESTIONS_LIST = get_questions_list_flat() or []
            logger.info(f"Loaded {len(AVAILABLE_BLOCKS)} blocks with questions")
            logger.info(f"Total questions: {len(QUESTIONS_LIST)}")
        else:
            logger.warning("get_questions_data() returned None or empty")
            QUESTIONS_DATA = {}
            AVAILABLE_BLOCKS = []
            QUESTIONS_LIST = []
            
    except ImportError as e:
        logger.error(f"Import error loading questions data: {e}")
        QUESTIONS_DATA = {}
        AVAILABLE_BLOCKS = []
        QUESTIONS_LIST = []
    except Exception as e:
        logger.error(f"Error loading questions data: {e}")
        QUESTIONS_DATA = {}
        AVAILABLE_BLOCKS = []
        QUESTIONS_LIST = []

# Вызываем инициализацию при импорте модуля
init_data()

# Добавьте отладочную проверку после init_data()
def check_data_loaded():
    """Проверяет, загружены ли данные."""
    global QUESTIONS_DATA, AVAILABLE_BLOCKS, QUESTIONS_LIST  # Объявляем global в начале
    
    if not QUESTIONS_DATA:
        logger.error("CRITICAL: QUESTIONS_DATA is empty after init!")
        
        # Проверяем путь к файлу
        questions_file_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            'data', 
            'questions.json'
        )
        logger.error(f"QUESTIONS_FILE path: {questions_file_path}")
        logger.error(f"File exists: {os.path.exists(questions_file_path)}")
        
        # Попробуем загрузить напрямую
        try:
            from .loader import load_questions, get_stats
            data, flat_list = load_questions()
            if data:
                QUESTIONS_DATA = data
                AVAILABLE_BLOCKS = list(data.keys())
                QUESTIONS_LIST = flat_list or []
                logger.info("Successfully loaded questions directly")
                stats = get_stats()
                logger.info(f"Questions stats: {stats}")
            else:
                logger.error("load_questions() returned empty data")
        except Exception as e:
            logger.error(f"Error during direct load: {e}")
            import traceback
            logger.error(traceback.format_exc())
    else:
        logger.info(f"Data loaded successfully: {len(AVAILABLE_BLOCKS)} blocks, {len(QUESTIONS_LIST)} questions")

# Вызовите проверку
check_data_loaded()

async def cleanup_previous_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет предыдущие сообщения бота."""
    messages_to_delete = [
        'thinking_message_id',      # "Ищу вопрос..."
        'checking_message_id',      # "Проверяю ваш ответ..."
        'question_message_id',      # Сообщение с вопросом
        'feedback_message_id'       # Сообщение с результатом
    ]
    
    for msg_key in messages_to_delete:
        msg_id = context.user_data.pop(msg_key, None)
        if msg_id:
            try:
                await update.effective_message.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=msg_id
                )
            except Exception as e:
                logger.debug(f"Failed to delete {msg_key}: {e}")


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в тестовую часть из главного меню."""
    query = update.callback_query
    
    # Очищаем контекст от данных других модулей
    keys_to_remove = [
        'current_topic',
        'task19_current_topic', 
        'task20_current_topic',
        'task25_current_topic',
        'task24_current_topic'
    ]
    
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    
    # Устанавливаем флаг активного модуля
    context.user_data['active_module'] = 'test_part'
    
    # Убрана проверка подписки - она должна быть на уровне всего бота
    
    kb = keyboards.get_initial_choice_keyboard()
    await query.edit_message_text(
        "📚 <b>Тестовая часть ЕГЭ</b>\n\n"
        "Выберите режим работы:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /quiz - вход в тестовую часть."""
    
    # Очищаем контекст от других модулей
    keys_to_remove = [
        'current_topic',
        'task19_current_topic', 
        'task20_current_topic',
        'task25_current_topic',
        'task24_current_topic'
    ]
    
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    
    # Устанавливаем активный модуль
    context.user_data['active_module'] = 'test_part'
    
    # Убрана проверка подписки - она должна быть на уровне всего бота
    
    kb = keyboards.get_initial_choice_keyboard()
    await update.message.reply_text(
        "📚 <b>Тестовая часть ЕГЭ</b>\n\n"
        "Выберите режим работы:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def test_detailed_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальный анализ ошибок."""
    context.user_data['conversation_state'] = states.CHOOSING_MODE
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем все ошибки пользователя
    mistakes = await utils.get_user_mistakes(user_id)
    
    if not mistakes:
        text = "📊 <b>Детальный анализ</b>\n\nУ вас пока нет ошибок для анализа!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="test_part_progress")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return states.CHOOSING_MODE
    
    # Группируем ошибки по темам
    mistakes_by_topic = {}
    for mistake in mistakes:
        topic = mistake.get('topic', 'Без темы')
        if topic not in mistakes_by_topic:
            mistakes_by_topic[topic] = []
        mistakes_by_topic[topic].append(mistake)
    
    # Формируем отчет
    text = "📊 <b>Детальный анализ ошибок</b>\n\n"
    
    for topic, topic_mistakes in mistakes_by_topic.items():
        text += f"📌 <b>{topic}</b>\n"
        text += f"   Ошибок: {len(topic_mistakes)}\n"
        
        # Показываем типы ошибок
        error_types = {}
        for m in topic_mistakes:
            error_type = m.get('error_type', 'Неверный ответ')
            error_types[error_type] = error_types.get(error_type, 0) + 1
        
        for error_type, count in error_types.items():
            text += f"   • {error_type}: {count}\n"
        text += "\n"
    
    # Рекомендации
    text += "💡 <b>Рекомендации:</b>\n"
    if len(mistakes_by_topic) > 3:
        text += "• Сосредоточьтесь на 2-3 темах с наибольшим количеством ошибок\n"
    text += "• Используйте режим 'Работа над ошибками' для тренировки\n"
    text += "• Изучите теорию по проблемным темам\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Экспорт в CSV", callback_data="test_export_csv")],
        [InlineKeyboardButton("🔄 Работа над ошибками", callback_data="test_work_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="test_part_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE
@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_exam_num_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор режима по номеру ЕГЭ."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    # Устанавливаем активный модуль
    context.user_data['active_module'] = 'test_part'
    
    # Используем безопасную функцию для получения номеров
    all_nums = safe_cache_get_all_exam_numbers()
    
    if not all_nums:
        await query.answer("Нет доступных заданий", show_alert=True)
        return states.CHOOSING_MODE
    
    kb = keyboards.get_exam_num_keyboard(all_nums)
    await query.edit_message_text(
        "📋 <b>Выберите номер задания ЕГЭ:</b>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    context.user_data['mode'] = 'exam_num'
    return states.CHOOSING_EXAM_NUMBER

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_block_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор режима по блокам."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    # Устанавливаем активный модуль
    context.user_data['active_module'] = 'test_part'
    
    if not AVAILABLE_BLOCKS:
        await query.answer("Блоки не загружены", show_alert=True)
        return states.CHOOSING_MODE
    
    kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
    await query.edit_message_text(
        "📚 <b>Выберите блок тем:</b>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    context.user_data['mode'] = 'block'
    return states.CHOOSING_BLOCK

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_random_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайный вопрос из всей базы."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    # Устанавливаем активный модуль
    context.user_data['active_module'] = 'test_part'
    
    # Проверяем, загружены ли данные
    if not QUESTIONS_DATA:
        logger.error("QUESTIONS_DATA is empty!")
        await query.answer("❌ База вопросов не загружена", show_alert=True)
        # Показываем сообщение с инструкцией
        await query.edit_message_text(
            "❌ <b>База вопросов не загружена</b>\n\n"
            "Пожалуйста, обратитесь к администратору.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.get_initial_choice_keyboard()
        )
        return states.CHOOSING_MODE
    
    # Собираем все вопросы
    all_questions = []
    for block_data in QUESTIONS_DATA.values():
        for topic_questions in block_data.values():
            all_questions.extend(topic_questions)
    
    if not all_questions:
        await query.answer("❌ Нет доступных вопросов", show_alert=True)
        await query.edit_message_text(
            "❌ <b>Нет доступных вопросов</b>\n\n"
            "База данных пуста. Обратитесь к администратору.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.get_initial_choice_keyboard()
        )
        return states.CHOOSING_MODE
    
    await query.edit_message_text("⏳ Загружаю случайный вопрос...")
    
    # Выбираем вопрос
    question_data = await utils.choose_question(query.from_user.id, all_questions)
    if question_data:
        await send_question(query.message, context, question_data, "random_all")
        # ВАЖНО: Устанавливаем состояние пользователя
        from core.state_validator import state_validator
        state_validator.set_state(query.from_user.id, states.ANSWERING)
        return states.ANSWERING
    else:
        kb = keyboards.get_initial_choice_keyboard()
        await query.message.edit_text(
            "Вы ответили на все вопросы! 🎉\n\nВыберите режим:",
            reply_markup=kb
        )
        return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_BLOCK})
async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретного блока."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    block_name = query.data.split(":", 2)[2]
    if block_name not in AVAILABLE_BLOCKS:
        return states.CHOOSING_BLOCK
    
    context.user_data['selected_block'] = block_name
    
    # Показываем режим внутри блока
    kb = keyboards.get_mode_keyboard(block_name)
    await query.edit_message_text(
        f"Блок: {block_name}\nВыберите режим:",
        reply_markup=kb
    )
    return states.CHOOSING_MODE

@safe_handler()
async def show_progress_enhanced(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса с улучшенным UI."""
    user_id = update.effective_user.id
    
    # Получаем статистику из БД
    stats = await db.get_user_stats(user_id)
    streaks = await db.get_user_streaks(user_id)
    
    if not stats:
        greeting = get_personalized_greeting({'total_attempts': 0, 'streak': streaks.get('current_daily', 0)})
        text = greeting + MessageFormatter.format_welcome_message(
            "тестовую часть ЕГЭ",
            is_new_user=True
        )
    else:
        # Подсчет общей статистики
        total_correct = sum(correct for _, correct, _ in stats)
        total_answered = sum(total for _, _, total in stats)
        overall_percentage = (total_correct / total_answered * 100) if total_answered > 0 else 0
        
        # Топ темы
        top_results = []
        for topic, correct, total in sorted(stats, key=lambda x: x[1]/x[2] if x[2] > 0 else 0, reverse=True)[:3]:
            percentage = (correct / total * 100) if total > 0 else 0
            topic_name = TOPIC_NAMES.get(topic, topic)
            top_results.append({
                'topic': topic_name,
                'score': correct,
                'max_score': total
            })
        
        greeting = get_personalized_greeting({'total_attempts': total_answered, 'streak': streaks.get('current_daily', 0)})
        text = greeting + MessageFormatter.format_progress_message({
            'total_attempts': total_answered,
            'average_score': overall_percentage / 100 * 3,  # Преобразуем в шкалу 0-3
            'completed': len(stats),
            'total': len(TOPIC_NAMES),
            'total_time': 0,  # Можно добавить подсчет времени
            'top_results': top_results,
            'current_average': overall_percentage,
            'previous_average': overall_percentage - 5  # Для демонстрации тренда
        }, "тестовой части")
        
        # Добавляем стрики
        if streaks:
            text += f"\n\n<b>🔥 Серии:</b>\n"
            text += UniversalUIComponents.format_statistics_tree({
                'Дней подряд': streaks.get('current_daily', 0),
                'Рекорд дней': streaks.get('max_daily', 0),
                'Правильных подряд': streaks.get('current_correct', 0),
                'Рекорд правильных': streaks.get('max_correct', 0)
            })
    
    # Адаптивная клавиатура
    kb = AdaptiveKeyboards.create_progress_keyboard(
        has_detailed_stats=bool(stats),
        can_export=bool(stats),
        module_code="test"
    )
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

@safe_handler()
@validate_state_transition({states.ANSWERING})
async def check_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка ответа пользователя."""
    
    # Проверяем активный модуль
    if context.user_data.get('active_module') != 'test_part':
        return states.ANSWERING
    
    # Дополнительная проверка состояния
    from core.state_validator import state_validator
    user_id = update.effective_user.id
    current_state = state_validator.get_current_state(user_id)
    
    if current_state != states.ANSWERING:
        # Если состояние не установлено, устанавливаем его
        state_validator.set_state(user_id, states.ANSWERING)
    
    # АНИМИРОВАННОЕ СООБЩЕНИЕ ПРОВЕРКИ
    thinking_msg = await show_thinking_animation(
        update.message,
        text="Проверяю ваш ответ"
    )
    
    # Сохраняем ID для удаления
    context.user_data['checking_message_id'] = thinking_msg.message_id
    
    user_id = update.effective_user.id
    user_answer = update.message.text.strip()
    context.user_data['user_answer_message_id'] = update.message.message_id

    # Получаем текущий вопрос
    current_question_id = context.user_data.get('current_question_id')
    
    if not current_question_id:
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        await update.message.reply_text("Ошибка: вопрос не найден.")
        return ConversationHandler.END
    
    # Получаем данные вопроса
    question_data = context.user_data.get(f'question_{current_question_id}')
    
    if not question_data:
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        await update.message.reply_text("Ошибка: данные вопроса не найдены.")
        return ConversationHandler.END
    
    # Обрабатываем ответ
    try:
        correct_answer = question_data.get('answer', '').strip()
        is_correct = user_answer.lower() == correct_answer.lower()
        
        # Получаем информацию о вопросе
        question_id = question_data.get('id')
        topic = question_data.get('topic')
        
        # Обновляем БД
        if topic and topic != "N/A":
            await db.update_progress(user_id, topic, is_correct)
        
        if question_id:
            await db.record_answered(user_id, question_id)
        
        if not is_correct and question_id:
            await db.record_mistake(user_id, question_id)
        
        # Обновляем стрики
        daily_current, daily_max = await db.update_daily_streak(user_id)
        
        if is_correct:
            correct_current, correct_max = await db.update_correct_streak(user_id)
        else:
            await db.reset_correct_streak(user_id)
            correct_current = 0
            streaks = await db.get_user_streaks(user_id)
            correct_max = streaks.get('max_correct', 0)
        
        # Сохраняем старый стрик
        old_correct_streak = context.user_data.get('correct_streak', 0)
        context.user_data['correct_streak'] = correct_current
        
        # Получаем дополнительные данные
        last_mode = context.user_data.get('last_mode', 'random')
        exam_number = context.user_data.get('current_exam_number')
        selected_topic = context.user_data.get('selected_topic')
        selected_block = context.user_data.get('selected_block')
        
        # Мотивационная фраза
        motivational_phrase = None
        try:
            if not is_correct:
                motivational_phrase = await utils.get_random_motivational_phrase()
        except Exception:
            pass
        
        # Статистика
        stats = await db.get_user_stats(user_id)
        total_correct = sum(correct for _, correct, _ in stats) if stats else 0
        total_answered = sum(total for _, _, total in stats) if stats else 0
        
        # ФОРМИРУЕМ КРАСИВЫЙ ФИДБЕК
        if is_correct:
            # ПРАВИЛЬНЫЙ ОТВЕТ
            feedback = f"<b>{utils.get_random_correct_phrase()}</b>\n"
            feedback += "─" * 30 + "\n\n"
            
            # Прогресс с визуализацией
            if last_mode == 'exam_num' and exam_number:
                questions_with_num = safe_cache_get_by_exam_num(exam_number)
                total_in_mode = len(questions_with_num)
                # Считаем правильные в этом задании
                exam_correct = 0
                for t, c, total in stats:
                    for q in questions_with_num:
                        if q.get('topic') == t:
                            exam_correct += c
                            break
                progress_bar = create_visual_progress(exam_correct, total_in_mode)
                feedback += f"📊 <b>Задание №{exam_number}:</b>\n"
                feedback += f"{progress_bar}\n"
                feedback += f"Правильных: {exam_correct}/{total_in_mode}\n\n"
            elif last_mode == 'topic' and selected_topic:
                for t, c, total in stats:
                    if t == selected_topic:
                        progress_bar = create_visual_progress(c, total)
                        topic_name = TOPIC_NAMES.get(selected_topic, selected_topic)
                        feedback += f"📊 <b>{topic_name}:</b>\n"
                        feedback += f"{progress_bar}\n"
                        feedback += f"Правильных: {c}/{total}\n\n"
                        break
            else:
                progress_bar = create_visual_progress(total_correct, total_answered)
                feedback += f"📊 <b>Общий прогресс:</b>\n"
                feedback += f"{progress_bar}\n"
                feedback += f"Правильных: {total_correct}/{total_answered}\n\n"
            
            # Стрики с деревом
            feedback += f"🔥 <b>Серии:</b>\n"
            feedback += f"├ 📅 Дней подряд: <b>{daily_current}</b>"
            if daily_current == daily_max and daily_max > 1:
                feedback += " 🏆"
            feedback += "\n"
            
            feedback += f"└ ✨ Правильных подряд: <b>{correct_current}</b>"
            if correct_current == correct_max and correct_max > 1:
                feedback += " 🏆"
            feedback += "\n"
            
            # Milestone
            milestone_phrase = utils.get_streak_milestone_phrase(correct_current)
            if milestone_phrase and correct_current > old_correct_streak:
                feedback += "\n" + "─" * 30 + "\n"
                feedback += f"{milestone_phrase}"
            
            # Новый рекорд
            if correct_current > old_correct_streak and correct_current == correct_max and correct_max > 1:
                feedback += "\n\n🎊 🎉 <b>НОВЫЙ ЛИЧНЫЙ РЕКОРД!</b> 🎉 🎊"
            
            if motivational_phrase:
                feedback += "\n\n" + "─" * 30 + "\n"
                feedback += f"💫 <i>{motivational_phrase}</i>"
                
        else:
            # НЕПРАВИЛЬНЫЙ ОТВЕТ
            feedback = f"<b>{utils.get_random_incorrect_phrase()}</b>\n"
            feedback += "─" * 30 + "\n\n"
            
            feedback += f"❌ Ваш ответ: <code>{user_answer}</code>\n"
            feedback += f"✅ Правильный ответ: <b>{correct_answer}</b>\n\n"
            
            # Прогресс
            if last_mode == 'exam_num' and exam_number:
                questions_with_num = safe_cache_get_by_exam_num(exam_number)
                total_in_mode = len(questions_with_num)
                exam_correct = 0
                for t, c, total in stats:
                    for q in questions_with_num:
                        if q.get('topic') == t:
                            exam_correct += c
                            break
                progress_bar = create_visual_progress(exam_correct, total_in_mode)
                feedback += f"📊 <b>Задание №{exam_number}:</b>\n"
                feedback += f"{progress_bar}\n\n"
            elif last_mode == 'topic' and selected_topic:
                for t, c, total in stats:
                    if t == selected_topic:
                        progress_bar = create_visual_progress(c, total)
                        topic_name = TOPIC_NAMES.get(selected_topic, selected_topic)
                        feedback += f"📊 <b>{topic_name}:</b>\n"
                        feedback += f"{progress_bar}\n\n"
                        break
            else:
                progress_bar = create_visual_progress(total_correct, total_answered)
                feedback += f"📊 <b>Общий прогресс:</b>\n"
                feedback += f"{progress_bar}\n\n"
            
            # Стрики
            feedback += f"🔥 <b>Серии:</b>\n"
            feedback += f"├ 📅 Дней подряд: <b>{daily_current}</b>\n"
            
            if old_correct_streak > 0:
                feedback += f"└ ✨ Правильных подряд: <b>0</b> "
                feedback += f"(было {old_correct_streak})\n"
                feedback += f"\n💔 <i>Серия из {old_correct_streak} правильных ответов прервана!</i>"
                if correct_max > 0:
                    feedback += f"\n📈 <i>Ваш рекорд: {correct_max}</i>"
            else:
                feedback += f"└ ✨ Правильных подряд: <b>0</b>"
            
            if motivational_phrase:
                feedback += "\n\n" + "─" * 30 + "\n"
                feedback += f"💪 <i>{motivational_phrase}</i>"
        
        # Кнопки
        has_explanation = bool(question_data.get('explanation'))
        kb = keyboards.get_next_action_keyboard(last_mode, has_explanation=has_explanation)
        
        # Удаляем анимацию
        try:
            await thinking_msg.delete()
        except Exception as e:
            logger.debug(f"Failed to delete checking message: {e}")
        
        # Отправляем фидбек
        sent_msg = await update.message.reply_text(
            feedback,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        context.user_data['feedback_message_id'] = sent_msg.message_id
        context.user_data['last_answer_correct'] = is_correct
        
        return states.CHOOSING_NEXT_ACTION
        
    except Exception as e:
        logger.error(f"Error in check_answer: {e}")
        
        try:
            await thinking_msg.delete()
        except Exception:
            pass
            
        await update.message.reply_text("Произошла ошибка при проверке ответа")
        return ConversationHandler.END

@safe_handler()
@validate_state_transition({states.CHOOSING_NEXT_ACTION, states.ANSWERING})
async def handle_next_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после ответа."""
    query = update.callback_query
    
    # Всегда отвечаем на callback query в начале
    await query.answer()
    action = query.data
    
    # Проверяем, что action начинается с правильного префикса
    if not action.startswith("test_"):
        logger.warning(f"Unexpected action in handle_next_action: {action}")
        return states.CHOOSING_NEXT_ACTION
    
    if action == "test_next_show_explanation":
        # Показываем пояснение для последнего отвеченного вопроса
        current_question_id = context.user_data.get('current_question_id')
        if current_question_id:
            question_data = context.user_data.get(f'question_{current_question_id}')
            if question_data and question_data.get('explanation'):
                explanation_text = question_data['explanation']
                
                # Используем централизованную функцию конвертации markdown
                explanation_text = utils.md_to_html(explanation_text)
                
                # Используем HTML для пояснений
                formatted_text = f"💡 <b>Пояснение к вопросу</b>\n\n"
                formatted_text += explanation_text
                
                try:
                    sent_msg = await query.message.reply_text(
                        formatted_text,
                        parse_mode=ParseMode.HTML
                    )
                    # Добавляем это сообщение к списку для удаления
                    context.user_data.setdefault('extra_messages_to_delete', []).append(sent_msg.message_id)
                except Exception as e:
                    logger.error(f"Error sending explanation: {e}")
            else:
                await query.answer("Пояснение отсутствует", show_alert=True)
        else:
            await query.answer("Ошибка: вопрос не найден", show_alert=True)
        
        # ВАЖНО: Отвечаем на callback query
        await query.answer()
        return states.CHOOSING_NEXT_ACTION
    
    elif action == "test_next_continue":
        # Сначала отправляем сообщение "Загружаю..."
        try:
            loading_msg = await query.message.reply_text("⏳ Загружаю следующий вопрос...")
        except Exception as e:
            logger.error(f"Error sending loading message: {e}")
            return states.CHOOSING_NEXT_ACTION
        
        # Удаляем предыдущие сообщения используя централизованную функцию
        await utils.purge_old_messages(context, query.message.chat_id, keep_id=loading_msg.message_id)
        
        # Очищаем все данные вопросов
        logger.info("Clearing all question data before loading next question")
        keys_to_remove = []
        for key in context.user_data.keys():
            if key.startswith('question_'):
                keys_to_remove.append(key)
        for key in keys_to_remove:
            context.user_data.pop(key, None)
        
        # Продолжаем в том же режиме
        last_mode = context.user_data.get('last_mode')
        
        if last_mode == 'random_all':
            all_questions = []
            for block_data in QUESTIONS_DATA.values():
                for topic_questions in block_data.values():
                    all_questions.extend(topic_questions)
            
            question_data = await utils.choose_question(query.from_user.id, all_questions)
            if question_data:
                await send_question(loading_msg, context, question_data, "random_all")
                return states.ANSWERING
            else:
                kb = keyboards.get_initial_choice_keyboard()
                await loading_msg.edit_text(
                    "Вы ответили на все вопросы! 🎉\n\nВыберите режим:",
                    reply_markup=kb
                )
                return states.CHOOSING_MODE
        
        elif last_mode == 'exam_num':
            # Продолжаем с тем же номером ЕГЭ
            exam_number = context.user_data.get('current_exam_number')
            if exam_number:
                questions_with_num = safe_cache_get_by_exam_num(exam_number)
                
                question_data = await utils.choose_question(query.from_user.id, questions_with_num)
                if question_data:
                    await send_question(loading_msg, context, question_data, "exam_num")
                    return states.ANSWERING
                else:
                    kb = keyboards.get_initial_choice_keyboard()
                    await loading_msg.edit_text(
                        f"Вы ответили на все вопросы задания №{exam_number}! 🎉\n\nВыберите режим:",
                        reply_markup=kb
                    )
                    return states.CHOOSING_MODE
        
        elif last_mode == 'block':
            # Продолжаем с тем же блоком
            selected_block = context.user_data.get('selected_block')
            if selected_block:
                questions_in_block = safe_cache_get_by_block(selected_block)
                
                question_data = await utils.choose_question(query.from_user.id, questions_in_block)
                if question_data:
                    await send_question(loading_msg, context, question_data, "block")
                    return states.ANSWERING
                else:
                    kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
                    await loading_msg.edit_text(
                        f"Вы ответили на все вопросы в блоке '{selected_block}'! 🎉\n\nВыберите другой блок:",
                        reply_markup=kb
                    )
                    return states.CHOOSING_BLOCK
        
        elif last_mode == 'topic':
            # Продолжаем с той же темой
            selected_topic = context.user_data.get('selected_topic')
            selected_block = context.user_data.get('selected_block')
            
            if selected_topic and selected_block:
                questions_in_topic = safe_cache_get_by_topic(selected_topic)
                
                question_data = await utils.choose_question(query.from_user.id, questions_in_topic)
                if question_data:
                    await send_question(loading_msg, context, question_data, "topic")
                    return states.ANSWERING
                else:
                    topics = list(QUESTIONS_DATA.get(selected_block, {}).keys())
                    kb = keyboards.get_topics_keyboard(selected_block, topics)
                    await loading_msg.edit_text(
                        f"Вы ответили на все вопросы по теме! 🎉\n\nВыберите другую тему:",
                        reply_markup=kb
                    )
                    return states.CHOOSING_TOPIC
        
        elif last_mode == 'mistakes':
            # Продолжаем работу над ошибками
            context.user_data['current_mistake_index'] = context.user_data.get('current_mistake_index', 0) + 1
            await send_mistake_question(loading_msg, context)
            return states.REVIEWING_MISTAKES
        
    elif action == "test_next_change_topic":
        # Возврат к выбору режима
        # Сначала удаляем старые сообщения
        await utils.purge_old_messages(context, query.message.chat_id)
        
        kb = keyboards.get_initial_choice_keyboard()
        await query.message.reply_text(
            "📚 <b>Тестовая часть ЕГЭ</b>\n\n"
            "Выберите режим:",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_MODE
    
    elif action == "test_next_change_block":
        # В главное меню
        # Сначала удаляем старые сообщения
        await utils.purge_old_messages(context, query.message.chat_id)
        
        kb = build_main_menu()
        
        await query.message.reply_text(
            "👋 Что хотите потренировать?",
            reply_markup=kb
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    else:
        logger.warning(f"Неизвестное действие: {action}")
        return states.CHOOSING_NEXT_ACTION

async def cmd_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mistakes - работа над ошибками."""
    user_id = update.effective_user.id
    mistake_ids = await db.get_mistake_ids(user_id)
    
    if not mistake_ids:
        await update.message.reply_text("👍 У вас нет ошибок для повторения!")
        return ConversationHandler.END
    
    context.user_data['mistake_ids'] = list(mistake_ids)
    context.user_data['current_mistake_index'] = 0
    context.user_data['user_id'] = user_id
    
    await update.message.reply_text(
        f"Начинаем работу над ошибками. Всего: {len(mistake_ids)}"
    )
    
    # Отправляем первый вопрос
    await send_mistake_question(update.message, context)
    return states.REVIEWING_MISTAKES

async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /score - показ статистики."""
    user_id = update.effective_user.id
    
    # Получаем данные
    stats_raw = await db.get_user_stats(user_id)
    mistake_ids = await db.get_mistake_ids(user_id)
    streaks = await db.get_user_streaks(user_id)
    
    # Формируем текст
    text = "📊 <b>Ваша статистика:</b>\n\n"
    
    if stats_raw:
        # Группируем по блокам
        scores_by_block = {}
        for topic, correct, total in stats_raw:
            block_name = "Неизвестный блок"
            for block, topics in QUESTIONS_DATA.items():
                if topic in topics:
                    block_name = block
                    break
            
            if block_name not in scores_by_block:
                scores_by_block[block_name] = {
                    'correct': 0, 'total': 0, 'topics': []
                }
            
            scores_by_block[block_name]['correct'] += correct
            scores_by_block[block_name]['total'] += total
            
            percentage = (correct / total * 100) if total > 0 else 0
            indicator = "✅" if percentage >= 80 else "🟡" if percentage >= 50 else "🔴"
            scores_by_block[block_name]['topics'].append(
                f"  {indicator} Тема {topic}: {correct}/{total} ({percentage:.1f}%)"
            )
        
        # Выводим по блокам
        for block_name, data in sorted(scores_by_block.items()):
            block_perc = (data['correct'] / data['total'] * 100) if data['total'] > 0 else 0
            text += f"📌 <b>{block_name}</b> ({block_perc:.1f}%)\n"
            text += "\n".join(data['topics']) + "\n\n"
    
    # Стрики
    text += "✨ <b>Стрики:</b>\n"
    text += f"  🔥 Дней подряд: {streaks.get('current_daily', 0)} (макс: {streaks.get('max_daily', 0)})\n"
    text += f"  🚀 Правильных подряд: {streaks.get('current_correct', 0)} (макс: {streaks.get('max_correct', 0)})\n\n"
    
    # Ошибки
    if mistake_ids:
        text += f"❗️ У вас {len(mistake_ids)} вопросов с ошибками.\n"
        text += "Используйте /mistakes для работы над ними."
    else:
        text += "👍 Отличная работа, ошибок нет!"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE, states.CHOOSING_BLOCK, states.CHOOSING_TOPIC, states.CHOOSING_EXAM_NUMBER})
async def back_to_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору режима тестовой части."""
    query = update.callback_query
    
    kb = keyboards.get_initial_choice_keyboard()
    await query.edit_message_text(
        "📚 <b>Тестовая часть ЕГЭ</b>\n\n"
        "Выберите режим:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    from core.menu_handlers import handle_to_main_menu
    return await handle_to_main_menu(update, context)
    
@safe_handler()
@validate_state_transition({states.CHOOSING_MODE, states.CHOOSING_BLOCK, states.CHOOSING_TOPIC, states.ANSWERING})
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору режима тестовой части из подменю."""
    query = update.callback_query
    
    kb = keyboards.get_initial_choice_keyboard()
    await query.edit_message_text(
        "📚 <b>Тестовая часть ЕГЭ</b>\n\n"
        "Выберите режим:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel - отмена действия."""
    kb = keyboards.get_initial_choice_keyboard()
    await update.message.reply_text(
        "Действие отменено. Выберите режим:",
        reply_markup=kb
    )
    return states.CHOOSING_MODE

async def send_question(message, context: ContextTypes.DEFAULT_TYPE,
                       question_data: dict, last_mode: str):
    """Отправка вопроса пользователю с поддержкой изображений и длинных текстов."""
    
    # Устанавливаем активный модуль
    context.user_data['active_module'] = 'test_part'
    
    # Сохраняем данные о вопросе
    question_id = question_data.get('id')
    context.user_data['current_question_id'] = question_id
    context.user_data[f'question_{question_id}'] = question_data
    context.user_data['last_mode'] = last_mode
    
    # Проверяем наличие обязательных полей
    required_fields = ['id', 'answer', 'type']
    missing_fields = [field for field in required_fields if not question_data.get(field)]
    
    if missing_fields:
        logger.error(f"Question missing required fields: {missing_fields}")
        error_msg = "❌ Ошибка: некорректные данные вопроса"
        
        if hasattr(message, 'edit_text'):
            await message.edit_text(error_msg)
        else:
            await message.reply_text(error_msg)
        return ConversationHandler.END
    
    # Очищаем данные предыдущих вопросов
    logger.info(f"Clearing old question data before sending new question {question_id}")
    keys_to_remove = []
    for key in context.user_data.keys():
        if key.startswith('question_') and key != f'question_{question_id}':
            keys_to_remove.append(key)
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    
    # Сохраняем данные вопроса под его ID
    context.user_data[f'question_{question_id}'] = question_data.copy()
    context.user_data['current_question_id'] = question_id
    context.user_data['last_mode'] = last_mode
    
    # Логирование для отладки
    logger.info(f"SENDING QUESTION: ID={question_id}, "
                f"Answer={question_data.get('answer')}, "
                f"Type={question_data.get('type')}, "
                f"Topic={question_data.get('topic')}, "
                f"Has image={bool(question_data.get('image_url'))}")
    
    # Добавляем информацию о блоке и теме
    if 'block' not in question_data and context.user_data.get('selected_block'):
        question_data['block'] = context.user_data['selected_block']
    if 'topic' not in question_data and context.user_data.get('selected_topic'):
        question_data['topic'] = context.user_data['selected_topic']
    
    # Сохраняем номер задания ЕГЭ для режима exam_num
    if last_mode == 'exam_num' and 'exam_number' in question_data:
        context.user_data['current_exam_number'] = question_data['exam_number']
    
    # ИСПРАВЛЕНО: Правильное получение user_id
    # Сначала пробуем получить из контекста (самый надежный способ)
    user_id = context.user_data.get('user_id')
    
    if not user_id:
        # Если нет в контексте, пробуем получить из сообщения
        if hasattr(message, 'from_user') and message.from_user:
            user_id = message.from_user.id
        elif hasattr(message, 'chat') and message.chat:
            user_id = message.chat.id
        else:
            # Крайний случай - пробуем найти в message.message
            if hasattr(message, 'message') and hasattr(message.message, 'chat'):
                user_id = message.message.chat.id
    
    # Проверка что user_id корректный (не ID бота)
    if not user_id:
        logger.error("Cannot determine user_id!")
        await message.reply_text("Ошибка: не удалось определить пользователя")
        return ConversationHandler.END
    
    # Сохраняем user_id в контекст для будущего использования
    context.user_data['user_id'] = user_id
    
    logger.debug(f"Determined user_id: {user_id}")
    
    # Форматируем текст вопроса
    text = utils.format_question_text(question_data)
    
    # Проверяем наличие изображения
    image_url = question_data.get('image_url')
    
    try:
        if image_url:
            import os
            
            # Проверяем существование файла
            if os.path.exists(image_url):
                # Проверяем длину текста для caption (максимум 1024 символа)
                MAX_CAPTION_LENGTH = 1024
                
                if len(text) <= MAX_CAPTION_LENGTH:
                    # Текст помещается в caption - отправляем как обычно
                    if hasattr(message, 'reply_photo'):
                        # Это обычное сообщение
                        with open(image_url, 'rb') as photo:
                            sent_msg = await message.reply_photo(
                                photo=photo,
                                caption=text,
                                parse_mode=ParseMode.HTML
                            )
                    else:
                        # Это CallbackQuery - нужно отправить новое сообщение
                        try:
                            await message.delete()
                        except:
                            pass
                        
                        with open(image_url, 'rb') as photo:
                            sent_msg = await context.bot.send_photo(
                                chat_id=user_id,
                                photo=photo,
                                caption=text,
                                parse_mode=ParseMode.HTML
                            )
                    
                    if sent_msg:
                        context.user_data['current_question_message_id'] = sent_msg.message_id
                else:
                    # Текст слишком длинный - отправляем изображение и текст отдельно
                    logger.info(f"Text too long ({len(text)} chars), sending image and text separately")
                    
                    # Удаляем старое сообщение если это CallbackQuery
                    if hasattr(message, 'delete'):
                        try:
                            await message.delete()
                        except Exception as e:
                            logger.debug(f"Could not delete message: {e}")
                    
                    # Сначала отправляем изображение без текста или с коротким заголовком
                    with open(image_url, 'rb') as photo:
                        photo_msg = await context.bot.send_photo(
                            chat_id=user_id,
                            photo=photo,
                            caption="📊 График к заданию"
                        )
                    
                    # Затем отправляем текст вопроса
                    text_msg = await context.bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Сохраняем ID текстового сообщения как основного
                    if text_msg:
                        context.user_data['current_question_message_id'] = text_msg.message_id
                        # Также сохраняем ID сообщения с фото для возможного удаления
                        context.user_data['current_photo_message_id'] = photo_msg.message_id
            else:
                # Файл не найден, отправляем только текст с предупреждением
                logger.error(f"Image file not found: {image_url}")
                text = "⚠️ Изображение не найдено\n\n" + text
                
                if hasattr(message, 'edit_text'):
                    await message.edit_text(text, parse_mode=ParseMode.HTML)
                    context.user_data['current_question_message_id'] = message.message_id
                else:
                    sent_msg = await message.reply_text(text, parse_mode=ParseMode.HTML)
                    if sent_msg:
                        context.user_data['current_question_message_id'] = sent_msg.message_id
        else:
            # Нет изображения - используем стандартную логику
            if hasattr(message, 'edit_text'):
                # Это CallbackQuery - редактируем сообщение
                await message.edit_text(text, parse_mode=ParseMode.HTML)
                context.user_data['current_question_message_id'] = message.message_id
            else:
                # Это обычное сообщение - отправляем новое
                sent_msg = await message.reply_text(text, parse_mode=ParseMode.HTML)
                if sent_msg:
                    context.user_data['current_question_message_id'] = sent_msg.message_id
                    
    except Exception as e:
        logger.error(f"Ошибка отправки вопроса: {e}")
        try:
            if hasattr(message, 'edit_text'):
                await message.edit_text("Ошибка при отображении вопроса. Попробуйте еще раз.")
            else:
                await message.reply_text("Ошибка при отображении вопроса. Попробуйте еще раз.")
        except:
            pass
        return ConversationHandler.END
    
    # Устанавливаем состояние пользователя
    from core.state_validator import state_validator
    state_validator.set_state(user_id, states.ANSWERING)
    
    return states.ANSWERING

@safe_handler()
async def handle_unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик неизвестных callback_data в test_part."""
    query = update.callback_query
    
    # Логируем неизвестный callback
    logger.warning(f"Неизвестный callback в test_part: {query.data}")
    
    # Проверяем, не наши ли это кнопки
    if query.data in ["test_export_csv", "test_work_mistakes"]:
        logger.error(f"ВНИМАНИЕ: callback {query.data} попал в handle_unknown_callback!")
    
    await query.answer("Функция временно недоступна", show_alert=True)
    
    # Возвращаем текущее состояние
    return states.CHOOSING_MODE

async def cmd_export_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /export - экспорт статистики в CSV файл."""
    user_id = update.effective_user.id
    
    try:
        # Генерируем CSV
        csv_content = await utils.export_user_stats_csv(user_id)
        
        # Отправляем как файл
        from io import BytesIO
        file_data = BytesIO(csv_content.encode('utf-8-sig'))  # utf-8-sig для корректного отображения в Excel
        file_data.name = f"statistics_{user_id}.csv"
        
        await update.message.reply_document(
            document=file_data,
            filename=f"statistics_{user_id}_{datetime.now().strftime('%Y%m%d')}.csv",
            caption="📊 Ваша статистика в формате CSV\n\nОткройте файл в Excel или Google Sheets для просмотра"
        )
        
    except Exception as e:
        logger.error(f"Ошибка экспорта статистики для user {user_id}: {e}")
        await update.message.reply_text("Не удалось экспортировать статистику. Попробуйте позже.")

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /report - детальный отчет о прогрессе."""
    user_id = update.effective_user.id
    
    try:
        report = await utils.generate_detailed_report(user_id)
        await update.message.reply_text(report, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка генерации отчета для user {user_id}: {e}")
        await update.message.reply_text("Не удалось сгенерировать отчет. Попробуйте позже.")

async def send_mistake_question(message, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет вопрос из списка ошибок."""
    mistake_ids = context.user_data.get('mistake_ids', [])
    current_index = context.user_data.get('current_mistake_index', 0)
    
    if current_index >= len(mistake_ids):
        # Все ошибки пройдены
        kb = keyboards.get_mistakes_finish_keyboard()
        
        text = "✅ <b>Работа над ошибками завершена!</b>\n\n"
        text += f"Исправлено ошибок: {context.user_data.get('mistakes_corrected', 0)}\n"
        text += f"Осталось ошибок: {len(mistake_ids)}"
        
        if hasattr(message, 'edit_text'):
            await message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            await message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        
        return states.CHOOSING_MODE
    
    # Получаем вопрос
    question_id = mistake_ids[current_index]
    question_data = utils.find_question_by_id(question_id)
    
    if not question_data:
        # Вопрос не найден, пропускаем
        context.user_data['current_mistake_index'] = current_index + 1
        return await send_mistake_question(message, context)
    
    # Отправляем вопрос
    await send_question(message, context, question_data, "mistakes")
    
    # ДОБАВИТЬ: Устанавливаем состояние пользователя
    # Получаем user_id из контекста
    user_id = context.user_data.get('user_id')
    if user_id:
        from core.state_validator import state_validator
        state_validator.set_state(user_id, states.REVIEWING_MISTAKES)
    
    return states.REVIEWING_MISTAKES

@safe_handler()
@validate_state_transition({states.REVIEWING_MISTAKES})
async def handle_mistake_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа в режиме ошибок с анимацией."""
    
    # ИСПОЛЬЗУЕМ АНИМИРОВАННОЕ СООБЩЕНИЕ
    checking_msg = await show_thinking_animation(
        update.message,
        text="Проверяю ваш ответ"
    )
    
    user_answer = update.message.text.strip()
    current_question_id = context.user_data.get('current_question_id')
    user_id = update.effective_user.id
    context.user_data['user_answer_message_id'] = update.message.message_id
    if not current_question_id:
        await checking_msg.delete()
        await update.message.reply_text("Ошибка: вопрос не найден.")
        return states.CHOOSING_MODE
    
    # Получаем данные вопроса
    question_data = context.user_data.get(f'question_{current_question_id}')
    
    if not question_data:
        await checking_msg.delete()
        await update.message.reply_text("Ошибка: данные вопроса не найдены.")
        return states.CHOOSING_MODE
    
    # Проверяем ответ
    correct_answer = str(question_data.get('answer', ''))
    question_type = question_data.get('type', 'multiple_choice')
    topic = question_data.get('topic')
    
    is_correct = utils.normalize_answer(user_answer, question_type) == \
                 utils.normalize_answer(correct_answer, question_type)
    
    # Обновляем прогресс
    await db.update_progress(user_id, topic, is_correct)
    
    # Если правильно - удаляем из ошибок
    if is_correct:
        await db.delete_mistake(user_id, current_question_id)
        # Удаляем из списка в контексте
        mistake_ids = context.user_data.get('mistake_ids', [])
        current_index = context.user_data.get('current_mistake_index', 0)
        if 0 <= current_index < len(mistake_ids):
            mistake_ids.pop(current_index)
            context.user_data['mistake_ids'] = mistake_ids
    else:
        # Если неправильно, переходим к следующей ошибке
        context.user_data['current_mistake_index'] = context.user_data.get('current_mistake_index', 0) + 1
    
    # Формируем ответ
    if is_correct:
        feedback = f"✅ <b>Правильно!</b> Ошибка исправлена."
    else:
        feedback = f"❌ <b>Неправильно!</b>\n\n"
        feedback += f"Ваш ответ: {user_answer}\n"
        feedback += f"Правильный ответ: <b>{correct_answer}</b>"
    
    # Показываем кнопки навигации
    mistake_ids = context.user_data.get('mistake_ids', [])
    current_index = context.user_data.get('current_mistake_index', 0)
    
    kb_buttons = []
    
    # Кнопка пояснения если есть
    if question_data.get('explanation'):
        kb_buttons.append([
            InlineKeyboardButton(
                "💡 Пояснение",
                callback_data="test_next_show_explanation",
            )
        ])
    
    # Кнопки навигации
    if current_index < len(mistake_ids):
        kb_buttons.append([
            InlineKeyboardButton(
                "➡️ Следующая ошибка",
                callback_data="test_next_continue",
            )
        ])
    else:
        kb_buttons.append([
            InlineKeyboardButton(
                "✅ Завершить",
                callback_data="test_mistake_finish",
            )
        ])
    
    kb_buttons.append([
        InlineKeyboardButton(
            "🔙 К выбору режима",
            callback_data="test_next_change_topic",
        )
    ])
    
    kb = InlineKeyboardMarkup(kb_buttons)
    
    # ВАЖНО: Удаляем сообщение "Проверяю..." перед отправкой фидбека
    try:
        await checking_msg.delete()
    except Exception:
        pass
    
    # Отправляем фидбек
    sent_msg = await update.message.reply_text(
        feedback,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    context.user_data['feedback_message_id'] = sent_msg.message_id
    context.user_data['last_mode'] = 'mistakes'
    
    return states.CHOOSING_NEXT_ACTION

@safe_handler()
@validate_state_transition({states.REVIEWING_MISTAKES, states.CHOOSING_MODE})
async def mistake_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по ошибкам."""
    query = update.callback_query
    
    action = query.data

    if action == "test_mistake_finish":
        kb = keyboards.get_initial_choice_keyboard()
        await query.edit_message_text(
            "✅ Работа над ошибками завершена!\n\n"
            "Выберите режим:",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_MODE
    
    return states.REVIEWING_MISTAKES
    
@safe_handler()
@validate_state_transition({states.CHOOSING_MODE, states.CHOOSING_EXAM_NUMBER})
async def select_exam_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретного номера задания."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    
    try:
        exam_number = int(query.data.split(":", 2)[2])
    except (ValueError, IndexError):
        return states.CHOOSING_EXAM_NUMBER
    
    # Сохраняем выбранный номер
    context.user_data['current_exam_number'] = exam_number
    
    # Собираем вопросы с этим номером
    questions_with_num = safe_cache_get_by_exam_num(exam_number)
    
    if not questions_with_num:
        return states.CHOOSING_EXAM_NUMBER
    
    await query.edit_message_text(f"⏳ Загружаю вопрос задания №{exam_number}...")
    
    # Выбираем вопрос
    question_data = await utils.choose_question(query.from_user.id, questions_with_num)
    if question_data:
        await send_question(query.message, context, question_data, "exam_num")
        # Добавить эти строки:
        from core.state_validator import state_validator
        state_validator.set_state(query.from_user.id, states.ANSWERING)
        return states.ANSWERING
    else:
        kb = keyboards.get_initial_choice_keyboard()
        await query.message.edit_text(
            f"Вы ответили на все вопросы задания №{exam_number}! 🎉\n\nВыберите режим:",
            reply_markup=kb
        )
        return states.CHOOSING_MODE
        
@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_mode_random_in_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайный вопрос из выбранного блока."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    selected_block = context.user_data.get('selected_block')
    if not selected_block or selected_block not in QUESTIONS_DATA:
        await query.answer("❌ Блок не выбран", show_alert=True)
        return states.CHOOSING_BLOCK
    
    questions_in_block = safe_cache_get_by_block(selected_block)
    
    if not questions_in_block:
        await query.answer("❌ В блоке нет вопросов", show_alert=True)
        kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
        await query.edit_message_text(
            f"❌ В блоке '{selected_block}' нет доступных вопросов.\n\nВыберите другой блок:",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_BLOCK
    
    await query.edit_message_text("⏳ Загружаю случайный вопрос из блока...")
    
    question_data = await utils.choose_question(query.from_user.id, questions_in_block)
    if question_data:
        await send_question(query.message, context, question_data, "block")
        # Устанавливаем состояние
        from core.state_validator import state_validator
        state_validator.set_state(query.from_user.id, states.ANSWERING)
        return states.ANSWERING
    else:
        kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
        await query.message.edit_text(
            f"Вы ответили на все вопросы в блоке '{selected_block}'! 🎉\n\nВыберите другой блок:",
            reply_markup=kb
        )
        return states.CHOOSING_BLOCK

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_mode_topic_in_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор темы в блоке."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    selected_block = context.user_data.get('selected_block')
    if not selected_block or selected_block not in QUESTIONS_DATA:
        return states.CHOOSING_BLOCK
    
    topics = list(QUESTIONS_DATA[selected_block].keys())
    if not topics:
        return states.CHOOSING_MODE
    
    kb = keyboards.get_topics_keyboard(selected_block, topics)
    await query.edit_message_text(
        "Выберите тему:",
        reply_markup=kb
    )
    return states.CHOOSING_TOPIC

@safe_handler()
@validate_state_transition({states.CHOOSING_TOPIC})
async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    selected_topic = query.data.replace("topic:", "")
    selected_block = context.user_data.get('selected_block')
    
    if not selected_block or not selected_topic:
        return states.CHOOSING_TOPIC
    
    questions_in_topic = safe_cache_get_by_topic(selected_topic)
    if not questions_in_topic:
        return states.CHOOSING_TOPIC
    
    context.user_data['selected_topic'] = selected_topic
    
    await query.edit_message_text("⏳ Загружаю вопрос по теме...")
    
    question_data = await utils.choose_question(query.from_user.id, questions_in_topic)
    if question_data:
        await send_question(query.message, context, question_data, "topic")
        # Добавить эти строки:
        from core.state_validator import state_validator
        state_validator.set_state(query.from_user.id, states.ANSWERING)
        return states.ANSWERING
    else:
        topics = list(QUESTIONS_DATA[selected_block].keys())
        kb = keyboards.get_topics_keyboard(selected_block, topics)
        await query.message.edit_text(
            f"Вы ответили на все вопросы по теме! 🎉\n\nВыберите другую тему:",
            reply_markup=kb
        )
        return states.CHOOSING_TOPIC

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в режим работы над ошибками."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    # Устанавливаем активный модуль
    context.user_data['active_module'] = 'test_part'
    
    user_id = query.from_user.id
    mistake_ids = await db.get_mistake_ids(user_id)
    
    if not mistake_ids:
        return states.CHOOSING_MODE
    
    context.user_data['mistake_ids'] = list(mistake_ids)
    context.user_data['current_mistake_index'] = 0
    context.user_data['user_id'] = user_id  # Сохраняем user_id для send_mistake_question
    
    await query.edit_message_text(
        f"🔧 <b>Работа над ошибками</b>\n\n"
        f"Найдено ошибок: {len(mistake_ids)}\n"
        f"Начинаем работу...",
        parse_mode=ParseMode.HTML
    )
    
    # Отправляем первый вопрос
    await send_mistake_question(query.message, context)
    return states.REVIEWING_MISTAKES
    
async def cmd_debug_streaks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /debug_streaks - показывает детальную информацию о стриках."""
    user_id = update.effective_user.id
    
    # Получаем стрики
    streaks = await db.get_user_streaks(user_id)
    
    # Получаем прямо из БД для проверки
    try:
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            cursor = await conn.execute(
                """SELECT current_daily_streak, max_daily_streak, 
                          current_correct_streak, max_correct_streak,
                          last_activity_date
                   FROM users WHERE user_id = ?""",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if row:
                text = f"🔍 <b>Отладка стриков для user {user_id}:</b>\n\n"
                text += f"<b>Из функции get_user_streaks:</b>\n"
                text += f"  current_daily: {streaks.get('current_daily', 'None')}\n"
                text += f"  max_daily: {streaks.get('max_daily', 'None')}\n"
                text += f"  current_correct: {streaks.get('current_correct', 'None')}\n"
                text += f"  max_correct: {streaks.get('max_correct', 'None')}\n\n"
                
                text += f"<b>Прямо из БД:</b>\n"
                text += f"  current_daily_streak: {row[0]}\n"
                text += f"  max_daily_streak: {row[1]}\n"
                text += f"  current_correct_streak: {row[2]}\n"
                text += f"  max_correct_streak: {row[3]}\n"
                text += f"  last_activity_date: {row[4]}\n"
            else:
                text = f"❌ Пользователь {user_id} не найден в БД"
                
    except Exception as e:
        text = f"❌ Ошибка при чтении БД: {e}"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def test_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику и прогресс пользователя."""
    query = update.callback_query
    
    # Используем существующую функцию cmd_score
    await cmd_score(query, context)
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def test_detailed_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает расширенную детальную статистику."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем все данные
    stats = await db.get_user_stats(user_id)
    mistakes = await utils.get_user_mistakes(user_id)
    
    if not stats:
        await query.answer("У вас пока нет статистики", show_alert=True)
        return states.CHOOSING_MODE
    
    # Создаем детальный анализ по каждой теме
    text = "📊 <b>Детальный анализ по темам</b>\n\n"
    
    # Сортируем темы по проценту успешности
    topics_analysis = []
    for topic, correct, total in stats:
        if total > 0:
            percentage = (correct / total * 100)
            topic_name = TOPIC_NAMES.get(topic, topic)
            topics_analysis.append((topic_name, correct, total, percentage))
    
    topics_analysis.sort(key=lambda x: x[3], reverse=True)
    
    # Группируем по уровню успешности
    excellent = [t for t in topics_analysis if t[3] >= 90]
    good = [t for t in topics_analysis if 70 <= t[3] < 90]
    average = [t for t in topics_analysis if 50 <= t[3] < 70]
    weak = [t for t in topics_analysis if t[3] < 50]
    
    # Отображаем по группам
    if excellent:
        text += "🌟 <b>Отличное владение:</b>\n"
        for topic_name, correct, total, percentage in excellent:
            text += f"• {topic_name}: {correct}/{total} ({percentage:.0f}%)\n"
        text += "\n"
    
    if good:
        text += "✅ <b>Хороший уровень:</b>\n"
        for topic_name, correct, total, percentage in good:
            text += f"• {topic_name}: {correct}/{total} ({percentage:.0f}%)\n"
        text += "\n"
    
    if average:
        text += "📝 <b>Средний уровень:</b>\n"
        for topic_name, correct, total, percentage in average:
            text += f"• {topic_name}: {correct}/{total} ({percentage:.0f}%)\n"
        text += "\n"
    
    if weak:
        text += "❗ <b>Требуют особого внимания:</b>\n"
        for topic_name, correct, total, percentage in weak:
            text += f"• {topic_name}: {correct}/{total} ({percentage:.0f}%)\n"
        text += "\n"
    
    # Анализ ошибок
    if mistakes:
        mistakes_by_topic = {}
        for mistake in mistakes:
            topic = mistake.get('topic', 'Без темы')
            if topic not in mistakes_by_topic:
                mistakes_by_topic[topic] = []
            mistakes_by_topic[topic].append(mistake)
        
        text += "📌 <b>Анализ ошибок:</b>\n"
        for topic, topic_mistakes in sorted(mistakes_by_topic.items(), 
                                          key=lambda x: len(x[1]), reverse=True)[:5]:
            text += f"• {topic}: {len(topic_mistakes)} ошибок\n"
    
    # Итоговые рекомендации
    text += "\n💡 <b>План действий:</b>\n"
    if weak:
        text += f"1. Изучите теорию по темам: {', '.join([t[0] for t in weak[:3]])}\n"
    if len(mistakes) > 5:
        text += "2. Пройдите «Работу над ошибками»\n"
    text += "3. Практикуйтесь ежедневно для поддержания формы\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Экспорт в CSV", callback_data="test_export_csv")],
        [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="test_work_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="test_part_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE
    
@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def detailed_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает простую наглядную статистику пользователя."""
    # Устанавливаем правильное состояние
    context.user_data['conversation_state'] = states.CHOOSING_MODE
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем статистику из БД
    stats = await db.get_user_stats(user_id)
    mistakes = await db.get_mistake_ids(user_id)
    streaks = await db.get_user_streaks(user_id)
    
    if not stats:
        # Для нового пользователя
        text = MessageFormatter.format_welcome_message(
            "тестовую часть ЕГЭ",
            is_new_user=True
        )
        kb = keyboards.get_initial_choice_keyboard()
    else:
        # Подсчет общей статистики
        total_correct = sum(correct for _, correct, _ in stats)
        total_answered = sum(total for _, _, total in stats)
        overall_percentage = (total_correct / total_answered * 100) if total_answered > 0 else 0
        
        # Находим проблемные темы (меньше 60% правильных)
        weak_topics = []
        for topic, correct, total in stats:
            if total > 0 and (correct / total) < 0.6:
                topic_name = TOPIC_NAMES.get(topic, topic)
                percentage = (correct / total * 100)
                weak_topics.append((topic_name, percentage))
        
        # Сортируем проблемные темы по проценту
        weak_topics.sort(key=lambda x: x[1])
        
        # Формируем текст статистики
        text = f"📊 <b>Ваш прогресс</b>\n\n"
        
        # Общий прогресс-бар
        progress_bar = UniversalUIComponents.create_progress_bar(
            total_correct, total_answered, width=15, show_percentage=True
        )
        text += f"<b>Общий прогресс:</b> {progress_bar}\n"
        text += f"✅ Правильно: {total_correct} из {total_answered}\n\n"
        
        # Стрики
        if streaks:
            text += f"<b>🔥 Серии:</b>\n"
            if streaks.get('current_daily', 0) > 0:
                text += f"• Дней подряд: {streaks['current_daily']} (рекорд: {streaks.get('max_daily', 0)})\n"
            if streaks.get('current_correct', 0) > 0:
                text += f"• Правильных подряд: {streaks['current_correct']} (рекорд: {streaks.get('max_correct', 0)})\n"
            text += "\n"
        
        # Проблемные темы (максимум 5)
        if weak_topics:
            text += "<b>📍 Требуют внимания:</b>\n"
            for topic_name, percentage in weak_topics[:5]:
                color = UniversalUIComponents.get_color_for_score(percentage, 100)
                text += f"{color} {topic_name}: {percentage:.0f}%\n"
            text += "\n"
        
        # Количество ошибок
        if len(mistakes) > 0:
            text += f"<b>❗ Ошибок для проработки:</b> {len(mistakes)}\n\n"
        
        # Рекомендации
        text += "💡 <b>Рекомендации:</b>\n"
        if len(mistakes) > 10:
            text += "• Используйте режим «Работа над ошибками»\n"
        if weak_topics:
            text += "• Изучите теорию по проблемным темам\n"
        if overall_percentage > 80:
            text += "• Отличный результат! Попробуйте более сложные темы\n"
        elif overall_percentage < 60:
            text += "• Уделите больше времени теории перед практикой\n"
        
        # Используем модифицированную клавиатуру
        kb = keyboards.get_progress_keyboard()
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def test_work_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает работу над ошибками из статистики."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем ошибки через utils (как в статистике)
    mistakes = await utils.get_user_mistakes(user_id)
    
    if not mistakes:
        text = "🎉 <b>Отлично!</b>\n\nУ вас нет ошибок для проработки!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="test_part_progress")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return states.CHOOSING_MODE
    
    # Извлекаем ID вопросов из ошибок
    mistake_ids = [m['question_id'] for m in mistakes]
    
    # Сохраняем данные для работы
    context.user_data['mode'] = 'mistakes'
    context.user_data['mistake_ids'] = mistake_ids
    context.user_data['mistake_queue'] = mistake_ids.copy()
    context.user_data['mistakes_total'] = len(mistake_ids)
    context.user_data['mistakes_completed'] = 0
    context.user_data['current_mistake_index'] = 0
    context.user_data['user_id'] = user_id
    
    text = f"""🔄 <b>Работа над ошибками</b>

У вас {len(mistake_ids)} вопросов с ошибками.

Сейчас вы будете проходить эти вопросы заново. 
При правильном ответе вопрос будет удален из списка ошибок.

Готовы начать?"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Начать", callback_data="test_start_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="test_part_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def test_export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт статистики в CSV."""
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer("Подготавливаю файл...")
    
    try:
        # Получаем данные
        mistakes = await utils.get_user_mistakes(user_id)
        stats = await db.get_user_stats(user_id)
        
        if not stats:
            await query.answer("У вас пока нет статистики для экспорта", show_alert=True)
            return states.CHOOSING_MODE
        
        # Создаем CSV в памяти с правильной кодировкой для Excel
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')  # Используем ; для лучшей совместимости с Excel
        
        # Заголовок документа
        writer.writerow(['ОТЧЕТ ПО ТЕСТОВОЙ ЧАСТИ ЕГЭ ПО ОБЩЕСТВОЗНАНИЮ'])
        writer.writerow([f'Дата формирования: {datetime.now().strftime("%d.%m.%Y %H:%M")}'])
        writer.writerow([f'ID пользователя: {user_id}'])
        writer.writerow([])  # Пустая строка
        
        # Общая статистика - заголовок раздела
        writer.writerow(['=' * 20 + ' ОБЩАЯ СТАТИСТИКА ' + '=' * 20])
        writer.writerow([])
        
        # Заголовки таблицы статистики
        writer.writerow(['Тема', 'Правильных ответов', 'Всего вопросов', 'Процент правильных', 'Оценка'])
        
        total_correct = 0
        total_answered = 0
        
        # Данные по темам с оценкой
        for topic, correct, answered in stats:
            percentage = (correct / answered * 100) if answered > 0 else 0
            topic_name = TOPIC_NAMES.get(topic, topic)
            
            # Определяем оценку
            if percentage >= 90:
                grade = 'Отлично'
            elif percentage >= 70:
                grade = 'Хорошо'
            elif percentage >= 50:
                grade = 'Удовлетворительно'
            else:
                grade = 'Требует внимания'
            
            writer.writerow([topic_name, correct, answered, f'{percentage:.1f}%', grade])
            total_correct += correct
            total_answered += answered
        
        # Итоговая строка
        writer.writerow([])
        total_percentage = (total_correct/total_answered*100 if total_answered > 0 else 0)
        writer.writerow(['ИТОГО:', total_correct, total_answered, f'{total_percentage:.1f}%', ''])
        writer.writerow([])
        
        # Детальный анализ ошибок
        if mistakes:
            writer.writerow(['=' * 20 + ' АНАЛИЗ ОШИБОК ' + '=' * 20])
            writer.writerow([])
            writer.writerow(['№', 'ID вопроса', 'Тема', 'Тип ошибки', 'Номер в ЕГЭ'])
            
            for idx, mistake in enumerate(mistakes, 1):
                writer.writerow([
                    idx,
                    mistake.get('question_id', 'N/A'),
                    mistake.get('topic', 'Без темы'),
                    mistake.get('error_type', 'Неверный ответ'),
                    mistake.get('exam_number', 'N/A')
                ])
        
        # Рекомендации
        writer.writerow([])
        writer.writerow(['=' * 20 + ' РЕКОМЕНДАЦИИ ' + '=' * 20])
        writer.writerow([])
        
        # Анализируем слабые темы
        weak_topics = []
        for topic, correct, answered in stats:
            if answered > 0 and (correct / answered) < 0.6:
                topic_name = TOPIC_NAMES.get(topic, topic)
                percentage = (correct / answered * 100)
                weak_topics.append((topic_name, percentage))
        
        if weak_topics:
            writer.writerow(['Темы, требующие особого внимания:'])
            for topic_name, percentage in sorted(weak_topics, key=lambda x: x[1]):
                writer.writerow([f'- {topic_name} ({percentage:.0f}% правильных ответов)'])
        
        if len(mistakes) > 10:
            writer.writerow(['- Рекомендуется использовать режим "Работа над ошибками"'])
        
        if total_percentage > 80:
            writer.writerow(['- Отличный результат! Попробуйте более сложные задания'])
        elif total_percentage < 60:
            writer.writerow(['- Уделите больше времени изучению теории'])
        
        # Готовим файл для отправки
        output.seek(0)
        # Используем UTF-8 BOM для корректного отображения в Excel
        bio = io.BytesIO()
        bio.write('\ufeff'.encode('utf-8'))  # BOM для Excel
        bio.write(output.getvalue().encode('utf-8'))
        bio.seek(0)
        bio.name = f'test_statistics_{user_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
        # Отправляем файл
        await query.message.reply_document(
            document=bio,
            caption="📊 <b>Ваша статистика экспортирована!</b>\n\n"
                    "💡 Совет: Откройте файл в Excel, выделите все ячейки (Ctrl+A) "
                    "и дважды кликните на границе между заголовками колонок для автоподбора ширины.",
            filename=bio.name,
            parse_mode=ParseMode.HTML
        )
        
        # Показываем сообщение об успехе
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="test_part_progress")
        ]])
        
        await query.message.reply_text(
            "✅ Отчет успешно создан и отправлен!",
            reply_markup=kb
        )
        
    except Exception as e:
        logger.error(f"Ошибка экспорта для пользователя {user_id}: {e}")
        await query.answer("Произошла ошибка при экспорте", show_alert=True)
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def work_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает режим работы над ошибками."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем список ID вопросов с ошибками
    mistake_ids = await db.get_mistake_ids(user_id)
    
    if not mistake_ids:
        text = "🎉 <b>Отлично!</b>\n\nУ вас нет ошибок для проработки!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ В меню", callback_data="test_back_to_mode")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return states.CHOOSING_MODE
    
    # Сохраняем режим и список ошибок
    context.user_data['mode'] = 'mistakes'
    context.user_data['mistake_queue'] = mistake_ids.copy()
    context.user_data['mistakes_total'] = len(mistake_ids)
    context.user_data['mistakes_completed'] = 0
    
    text = f"""🔄 <b>Работа над ошибками</b>

У вас {len(mistake_ids)} вопросов с ошибками.

Сейчас вы будете проходить эти вопросы заново. 
При правильном ответе вопрос будет удален из списка ошибок.

Готовы начать?"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Начать", callback_data="test_start_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="test_back_to_mode")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def test_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к работе над ошибками."""
    return await work_mistakes(update, context)

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def test_practice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход в режим практики."""
    # Запускаем случайные вопросы
    return await select_random_all(update, context)

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def test_start_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает работу над ошибками."""
    query = update.callback_query
    
    # Проверяем наличие очереди ошибок
    if 'mistake_queue' not in context.user_data:
        await query.answer("Ошибка: список вопросов не найден", show_alert=True)
        return states.CHOOSING_MODE
    
    # Отправляем первый вопрос из очереди ошибок
    await query.edit_message_text("⏳ Загружаю первый вопрос...")
    
    # Устанавливаем индекс текущей ошибки
    context.user_data['current_mistake_index'] = 0
    
    # Отправляем вопрос
    await send_mistake_question(query.message, context)
    
    return states.REVIEWING_MISTAKES

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет подписку пользователя."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем статус подписки
    user_data = await db.get_user_status(user_id)
    is_subscribed = user_data.get('is_subscribed', False)
    
    if is_subscribed:
        text = """✅ <b>Подписка активна</b>

У вас есть доступ ко всем функциям бота:
• Неограниченное количество вопросов
• Детальная статистика
• Экспорт отчетов
• Приоритетная поддержка"""
    else:
        text = """❌ <b>Подписка не активна</b>

В бесплатной версии доступно:
• До 50 вопросов в месяц
• Базовая статистика
• Основные режимы тренировки

Для полного доступа оформите подписку."""
    
    kb_buttons = []
    if not is_subscribed:
        kb_buttons.append([
            InlineKeyboardButton("💎 Оформить подписку", url="https://example.com/subscribe")
        ])
    
    kb_buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="test_back_to_mode")
    ])
    
    kb = InlineKeyboardMarkup(kb_buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def test_back_to_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору режима из подменю."""
    return await back_to_mode(update, context)

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в режим работы над ошибками."""
    query = update.callback_query
    context.user_data['user_id'] = query.from_user.id
    user_id = query.from_user.id
    mistake_ids = await db.get_mistake_ids(user_id)
    
    if not mistake_ids:
        await query.answer("У вас пока нет ошибок! 🎉", show_alert=True)
        return states.CHOOSING_MODE
    
    context.user_data['mistake_ids'] = list(mistake_ids)
    context.user_data['current_mistake_index'] = 0
    context.user_data['user_id'] = user_id
    
    await query.edit_message_text(
        f"🔧 <b>Работа над ошибками</b>\n\n"
        f"Найдено ошибок: {len(mistake_ids)}\n"
        f"Начинаем работу...",
        parse_mode=ParseMode.HTML
    )
    
    # Отправляем первый вопрос
    await send_mistake_question(query.message, context)
    return states.REVIEWING_MISTAKES

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики - просто запускаем случайные вопросы."""
    return await select_random_all(update, context)

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def reset_progress_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса прогресса."""
    query = update.callback_query
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, сбросить", callback_data="test_reset_do"),
            InlineKeyboardButton("❌ Отмена", callback_data="to_test_part_menu")
        ]
    ])
    
    await query.edit_message_text(
        "⚠️ <b>Вы уверены?</b>\n\n"
        "Это действие удалит весь ваш прогресс, включая:\n"
        "• Статистику по всем темам\n"
        "• Список ошибок\n"
        "• Все достижения и стрики\n\n"
        "Это действие нельзя отменить!",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def reset_progress_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполнение сброса прогресса test_part."""
    query = update.callback_query
    user_id = query.from_user.id
    
    try:
        # Сбрасываем данные в БД
        await db.reset_user_progress(user_id)
        
        # Очищаем ТОЛЬКО временные данные test_part
        keys_to_remove = [
            'mistake_ids',
            'current_mistake_index',
            'current_topic',
            'current_question_id',
            'user_id'
        ]
        
        for key in keys_to_remove:
            context.user_data.pop(key, None)
        
        # НЕ ТРОГАЕМ данные других модулей!
        
        # Устанавливаем активный модуль обратно
        context.user_data['active_module'] = 'test_part'
        
        kb = keyboards.get_initial_choice_keyboard()
        await query.edit_message_text(
            "✅ <b>Прогресс успешно сброшен!</b>\n\n"
            "Теперь вы можете начать заново.\n\n"
            "Выберите режим:",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error resetting progress for user {user_id}: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при сбросе прогресса.\n"
            "Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="to_test_part_menu")
            ]])
        )
    
    return states.CHOOSING_MODE

@safe_handler()
async def back_to_test_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню тестовой части."""
    query = update.callback_query
    
    # Устанавливаем активный модуль
    context.user_data['active_module'] = 'test_part'
    
    kb = keyboards.get_initial_choice_keyboard()
    await query.edit_message_text(
        "📚 <b>Тестовая часть ЕГЭ</b>\n\n"
        "Выберите режим:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE