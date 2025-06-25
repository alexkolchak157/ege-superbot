# test_part/handlers.py
import logging
import random
from datetime import datetime

import aiosqlite
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
from core.state_validator import validate_state_transition, state_validator
from . import keyboards, utils
from .loader import AVAILABLE_BLOCKS, QUESTIONS_DATA, QUESTIONS_DICT_FLAT
from .missing_handlers import (
    detailed_report,
    export_csv,
    work_mistakes,
    check_subscription,
)

try:
    from .cache import questions_cache
except ImportError:
    logging.warning("Модуль cache не найден, работаем без кеширования")
    questions_cache = None

logger = logging.getLogger(__name__)

# Безопасные функции для работы с кешем
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

# Инициализация данных
def init_data():
    """Вызывается после загрузки вопросов."""
    global QUESTIONS_DATA, AVAILABLE_BLOCKS
    from .loader import get_questions_data
    QUESTIONS_DATA = get_questions_data()
    AVAILABLE_BLOCKS = list(QUESTIONS_DATA.keys()) if QUESTIONS_DATA else []


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
@validate_state_transition({ConversationHandler.END, None})
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в тестовую часть из главного меню."""
    query = update.callback_query
    
    # Используем utils из локального модуля для проверки подписки
    if not await utils.check_subscription(query.from_user.id, context.bot):
        await utils.send_subscription_required(query, REQUIRED_CHANNEL)
        return ConversationHandler.END
    
    # Получаем статистику пользователя
    user_stats_by_topic = await db.get_user_stats(query.from_user.id)
    mistake_ids = await db.get_mistake_ids(query.from_user.id)
    mistake_count = len(mistake_ids)
    streaks = await db.get_user_streaks(query.from_user.id)

    # Агрегируем статистику из списка тем
    total_correct = 0
    total_answered = 0
    for topic, correct, total in user_stats_by_topic:
        total_correct += correct
        total_answered += total

    # Формируем статистику для адаптивного меню
    stats_for_menu = {
        'streak': streaks.get('current_correct', 0),
        'total_attempts': total_answered,
        'progress_percent': int((total_correct / total_answered) * 100) if total_answered > 0 else 0,
        'mistakes_count': mistake_count
    }

    # Приветственное сообщение
    is_new = total_answered == 0

    # Создаем адаптивное меню
    kb = AdaptiveKeyboards.create_menu_keyboard(
        user_stats=stats_for_menu,
        module_code="test"
    )

    # Приветственное сообщение
    is_new = total_answered == 0
    welcome_text = MessageFormatter.format_welcome_message(
        module_name="Тестовая часть ЕГЭ",
        is_new_user=is_new
    )

    await query.edit_message_text(
        welcome_text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({ConversationHandler.END, None})
async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /quiz - запуск тестовой части."""
    # Используем локальный utils
    if not await utils.check_subscription(update.effective_user.id, context.bot, REQUIRED_CHANNEL):
        await utils.send_subscription_required(update, REQUIRED_CHANNEL)
        return ConversationHandler.END
    
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
async def select_exam_num_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор режима по номеру ЕГЭ."""
    query = update.callback_query
    
    # Получаем доступные номера
    exam_numbers = safe_cache_get_all_exam_numbers()
    
    if not exam_numbers:
        await query.answer("Нет доступных заданий", show_alert=True)
        return states.CHOOSING_MODE
    
    kb = keyboards.get_exam_num_keyboard(exam_numbers)
    await query.edit_message_text(
        "Выберите номер задания:",
        reply_markup=kb
    )
    return states.CHOOSING_EXAM_NUMBER

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_block_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем."""
    query = update.callback_query
    
    if not AVAILABLE_BLOCKS:
        await query.answer("Нет доступных блоков", show_alert=True)
        return states.CHOOSING_MODE
    
    kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
    await query.edit_message_text(
        "Выберите блок тем:",
        reply_markup=kb
    )
    return states.CHOOSING_BLOCK

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_random_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайный вопрос из всех."""
    query = update.callback_query
    
    if not QUESTIONS_DICT_FLAT:
        await query.answer("Нет доступных вопросов", show_alert=True)
        return states.CHOOSING_MODE
    
    await query.edit_message_text("⏳ Загружаю случайный вопрос...")
    
    all_questions = list(QUESTIONS_DICT_FLAT.values())
    question_data = await utils.choose_question(query.from_user.id, all_questions)
    
    if question_data:
        await send_question(query.message, context, question_data, "random_all")
        return states.ANSWERING
    else:
        kb = keyboards.get_initial_choice_keyboard()
        await query.message.edit_text(
            "Вы ответили на все доступные вопросы! 🎉\n\nВыберите другой режим:",
            reply_markup=kb
        )
        return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в режим работы над ошибками."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем список ошибок
    mistake_ids = await db.get_mistake_ids(user_id)
    
    if not mistake_ids:
        text = "🎉 <b>Отлично!</b>\n\nУ вас нет ошибок для проработки!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ В меню", callback_data="to_test_part_menu")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return states.CHOOSING_MODE
    
    # Начинаем работу над ошибками
    context.user_data['mode'] = 'mistakes'
    context.user_data['mistake_queue'] = list(mistake_ids)
    context.user_data['mistakes_total'] = len(mistake_ids)
    context.user_data['mistakes_completed'] = 0
    context.user_data['current_mistake_index'] = 0
    
    # Отправляем первый вопрос
    await send_mistake_question(query.message, context)
    return states.REVIEWING_MISTAKES

@safe_handler()
@validate_state_transition({states.CHOOSING_BLOCK})
async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретного блока."""
    query = update.callback_query
    
    try:
        selected_block = query.data.split(":", 2)[2]
    except IndexError:
        return states.CHOOSING_BLOCK
    
    if selected_block not in QUESTIONS_DATA:
        await query.answer("Блок не найден", show_alert=True)
        return states.CHOOSING_BLOCK
    
    context.user_data['selected_block'] = selected_block
    
    kb = keyboards.get_mode_keyboard(selected_block)
    await query.edit_message_text(
        f"Выбран блок: {selected_block}\n\nВыберите режим:",
        reply_markup=kb
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_EXAM_NUMBER})
async def select_exam_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретного номера задания."""
    query = update.callback_query
    
    try:
        exam_number = int(query.data.split(":", 2)[2])
    except (ValueError, IndexError):
        return states.CHOOSING_EXAM_NUMBER
    
    # Сохраняем выбранный номер
    context.user_data['current_exam_number'] = exam_number
    context.user_data['mode'] = 'exam_num'
    
    # Собираем вопросы с этим номером
    questions_with_num = safe_cache_get_by_exam_num(exam_number)
    
    if not questions_with_num:
        await query.answer("Нет вопросов для этого номера", show_alert=True)
        return states.CHOOSING_EXAM_NUMBER
    
    await query.edit_message_text(f"⏳ Загружаю вопрос задания №{exam_number}...")
    
    # Выбираем вопрос
    question_data = await utils.choose_question(query.from_user.id, questions_with_num)
    if question_data:
        await send_question(query.message, context, question_data, "exam_num")
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
    
    selected_block = context.user_data.get('selected_block')
    if not selected_block or selected_block not in QUESTIONS_DATA:
        return states.CHOOSING_BLOCK
    
    context.user_data['mode'] = 'block'
    questions_in_block = safe_cache_get_by_block(selected_block)
    
    if not questions_in_block:
        await query.answer("Нет вопросов в блоке", show_alert=True)
        return states.CHOOSING_MODE
    
    await query.edit_message_text("⏳ Загружаю случайный вопрос из блока...")
    
    question_data = await utils.choose_question(query.from_user.id, questions_in_block)
    if question_data:
        await send_question(query.message, context, question_data, "block")
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
    
    selected_block = context.user_data.get('selected_block')
    if not selected_block or selected_block not in QUESTIONS_DATA:
        return states.CHOOSING_BLOCK
    
    topics = list(QUESTIONS_DATA[selected_block].keys())
    if not topics:
        await query.answer("Нет тем в блоке", show_alert=True)
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
    
    selected_topic = query.data.replace("topic:", "")
    selected_block = context.user_data.get('selected_block')
    
    if not selected_block or not selected_topic:
        return states.CHOOSING_TOPIC
    
    questions_in_topic = safe_cache_get_by_topic(selected_topic)
    if not questions_in_topic:
        await query.answer("Нет вопросов по теме", show_alert=True)
        return states.CHOOSING_TOPIC
    
    context.user_data['selected_topic'] = selected_topic
    context.user_data['mode'] = 'topic'
    
    await query.edit_message_text("⏳ Загружаю вопрос по теме...")
    
    question_data = await utils.choose_question(query.from_user.id, questions_in_topic)
    if question_data:
        await send_question(query.message, context, question_data, "topic")
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
@validate_state_transition({states.ANSWERING})
async def check_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка ответа пользователя."""
    user_id = update.effective_user.id
    user_answer = update.message.text.strip()
    
    # Показываем индикатор проверки
    thinking_msg = await update.message.reply_text("🤔 Проверяю ваш ответ...")
    context.user_data['thinking_message_id'] = thinking_msg.message_id
    
    # Получаем данные текущего вопроса
    current_question_id = context.user_data.get('current_question_id')
    if not current_question_id:
        logger.error(f"No current question ID for user {user_id}")
        await thinking_msg.edit_text("❌ Ошибка: не найден текущий вопрос")
        return ConversationHandler.END
    
    question_data = context.user_data.get(f'question_{current_question_id}')
    if not question_data:
        logger.error(f"No question data for ID {current_question_id}")
        await thinking_msg.edit_text("❌ Ошибка: данные вопроса не найдены")
        return ConversationHandler.END
    
    # Проверяем ответ
    correct_answer = str(question_data.get('answer', '')).strip()
    last_mode = context.user_data.get('last_mode', 'random')
    
    is_correct = utils.check_answer(user_answer, correct_answer)
    
    # Обновляем статистику
    await db.update_user_answer(
        user_id=user_id,
        question_id=current_question_id,
        is_correct=is_correct,
        user_answer=user_answer
    )
    
    # Получаем статистику стрика
    correct_streak = await db.get_correct_streak(user_id)
    correct_max = await db.get_correct_max(user_id)
    
    # Формируем ответ с универсальными компонентами
    if is_correct:
        # Визуализация оценки
        score_visual = UniversalUIComponents.create_score_visual(1, 1)
        
        # Форматированное сообщение
        feedback = MessageFormatter.format_result_message(
            score=1,
            max_score=1,
            topic=question_data.get('topic', 'Тестовая часть'),
            details={
                'Правильных подряд': f"🔥 {correct_streak}" if correct_streak > 1 else None,
                'Рекорд': f"🏆 {correct_max}" if correct_streak > correct_max else None
            }
        )
        
        # Добавляем milestone если есть
        milestone_phrase = utils.get_streak_milestone_phrase(correct_streak)
        if milestone_phrase:
            feedback += f"\n\n{milestone_phrase}"
    else:
        # Получаем мотивационную фразу
        motivational_phrase = utils.get_motivational_message()  # Предполагается, что функция определена в utils
        
        # Для неправильного ответа
        feedback = MessageFormatter.format_result_message(
            score=0,
            max_score=1,
            topic=question_data.get('topic', 'Тестовая часть'),
            details={
                'Ваш ответ': user_answer,
                'Правильный ответ': f"<b>{correct_answer}</b>"
            }
        )
        
        feedback += f"\n\n{motivational_phrase}"
        
        if correct_streak > 0:
            feedback += f"\n💔 Серия из {correct_streak} правильных ответов прервана"
        if correct_max > 0:
            feedback += f"\n📈 Ваш рекорд: {correct_max}"
    
    # Адаптивная клавиатура на основе результата
    kb = AdaptiveKeyboards.create_result_keyboard(
        score=1 if is_correct else 0,
        max_score=1,
        module_code="test"
    )
    
    # Отправляем ответ пользователю
    await thinking_msg.edit_text(feedback, reply_markup=kb, parse_mode='HTML')
    
    return states.ANSWERING

@safe_handler()
@validate_state_transition({states.CHOOSING_NEXT_ACTION})
async def handle_next_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после ответа."""
    query = update.callback_query
    
    # Удаляем сообщение "Проверяю ваш ответ..." если оно есть
    checking_msg_id = context.user_data.pop('checking_message_id', None)
    if checking_msg_id:
        try:
            await query.message.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=checking_msg_id
            )
        except Exception as e:
            logger.debug(f"Failed to delete checking message: {e}")
    
    action = query.data
    
    if action == "test_next_show_explanation":
        # Показываем пояснение
        current_question_id = context.user_data.get('current_question_id')
        if current_question_id:
            question_data = context.user_data.get(f'question_{current_question_id}')
            if question_data and question_data.get('explanation'):
                explanation_text = question_data['explanation']
                
                # Конвертируем markdown в HTML
                explanation_text = utils.md_to_html(explanation_text)
                
                formatted_text = f"💡 <b>Пояснение к вопросу</b>\n\n{explanation_text}"
                
                try:
                    sent_msg = await query.message.reply_text(
                        formatted_text,
                        parse_mode=ParseMode.HTML
                    )
                    # Добавляем это сообщение к списку для удаления
                    context.user_data.setdefault('extra_messages_to_delete', []).append(sent_msg.message_id)
                except Exception as e:
                    logger.error(f"Error sending explanation: {e}")
        return states.CHOOSING_NEXT_ACTION
    
    elif action == "test_next_continue":
        # Отправляем сообщение "Загружаю..."
        try:
            loading_msg = await query.message.reply_text("⏳ Загружаю следующий вопрос...")
        except Exception as e:
            logger.error(f"Error sending loading message: {e}")
            return states.CHOOSING_NEXT_ACTION
        
        # Удаляем предыдущие сообщения
        await utils.purge_old_messages(context, query.message.chat_id, keep_id=loading_msg.message_id)
        
        # Определяем режим и продолжаем
        last_mode = context.user_data.get('last_mode', 'random')
        
        if last_mode == 'random_all':
            # Случайный из всех
            all_questions = list(QUESTIONS_DICT_FLAT.values())
            question_data = await utils.choose_question(query.from_user.id, all_questions)
            if question_data:
                await send_question(loading_msg, context, question_data, "random_all")
                return states.ANSWERING
            else:
                kb = keyboards.get_initial_choice_keyboard()
                await loading_msg.edit_text(
                    "Вы ответили на все доступные вопросы! 🎉\n\nВыберите режим:",
                    reply_markup=kb
                )
                return states.CHOOSING_MODE
        
        elif last_mode == 'exam_num':
            # Продолжаем с тем же номером
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

@safe_handler()
@validate_state_transition({states.REVIEWING_MISTAKES})
async def handle_mistake_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа в режиме работы над ошибками."""
    user_id = update.effective_user.id
    user_answer = update.message.text.strip()
    
    # Показываем индикатор проверки
    thinking_msg = await update.message.reply_text("🤔 Проверяю ваш ответ...")
    context.user_data['thinking_message_id'] = thinking_msg.message_id
    
    # Получаем данные текущего вопроса
    current_question_id = context.user_data.get('current_question_id')
    if not current_question_id:
        await thinking_msg.edit_text("❌ Ошибка: не найден текущий вопрос")
        return ConversationHandler.END
    
    question_data = context.user_data.get(f'question_{current_question_id}')
    if not question_data:
        await thinking_msg.edit_text("❌ Ошибка: данные вопроса не найдены")
        return ConversationHandler.END
    
    # Проверяем ответ
    correct_answer = str(question_data.get('answer', '')).strip()
    is_correct = utils.check_answer(user_answer, correct_answer)
    
    # Обновляем статистику
    await db.update_user_answer(
        user_id=user_id,
        question_id=current_question_id,
        is_correct=is_correct,
        user_answer=user_answer
    )
    
    # Если ответ правильный, удаляем из ошибок
    if is_correct:
        await db.remove_from_mistakes(user_id, current_question_id)
        feedback = f"{utils.get_random_correct_phrase()}\n\n"
        feedback += "✅ Вопрос удален из списка ошибок!"
    else:
        feedback = f"{utils.get_random_incorrect_phrase()}\n\n"
        feedback += f"Ваш ответ: {user_answer}\n"
        feedback += f"Правильный ответ: <b>{correct_answer}</b>"
    
    # Показываем кнопки навигации
    mistake_queue = context.user_data.get('mistake_queue', [])
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
    if current_index < len(mistake_queue) - 1:
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
    
    sent_msg = await update.message.reply_text(
        feedback,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Удаляем индикатор
    await thinking_msg.delete()
    
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
@validate_state_transition({
    states.CHOOSING_MODE, 
    states.CHOOSING_BLOCK, 
    states.CHOOSING_TOPIC, 
    states.CHOOSING_EXAM_NUMBER,
    states.CHOOSING_NEXT_ACTION,
    states.ANSWERING
})
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

@safe_handler()
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel - отмена действия."""
    kb = keyboards.get_initial_choice_keyboard()
    await update.message.reply_text(
        "Действие отменено. Выберите режим:",
        reply_markup=kb
    )
    return states.CHOOSING_MODE

@safe_handler()
async def cmd_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mistakes - работа над ошибками."""
    user_id = update.effective_user.id
    mistake_ids = await db.get_mistake_ids(user_id)
    
    if not mistake_ids:
        await update.message.reply_text("👍 У вас нет ошибок для повторения!")
        return ConversationHandler.END
    
    context.user_data['mistake_queue'] = list(mistake_ids)
    context.user_data['current_mistake_index'] = 0
    context.user_data['mode'] = 'mistakes'
    
    await update.message.reply_text(
        f"Начинаем работу над ошибками. Всего: {len(mistake_ids)}"
    )
    
    # Отправляем первый вопрос
    await send_mistake_question(update.message, context)
    return states.REVIEWING_MISTAKES

@safe_handler()
async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /score - показ статистики."""
    user_id = update.effective_user.id
    
    user_stats_by_topic = await db.get_user_stats(user_id)
    streaks = await db.get_user_streaks(user_id)

    # Агрегируем статистику
    total_correct = 0
    total_answered = 0
    for topic, correct, total in user_stats_by_topic:
        total_correct += correct
        total_answered += total

    # Используем в тексте
    text = MessageFormatter.format_progress_message(
        stats={
            'completed': total_correct,
            'total': total_answered,
            'average_score': total_correct / max(total_answered, 1),
            'total_attempts': total_answered,
            'current_average': (total_correct / max(total_answered, 1)) * 100,
            'streak': streaks.get('current_correct', 0),
            'max_streak': streaks.get('max_correct', 0),
            'mistakes_count': mistake_count
        },
        module_name="Тестовая часть"
    )

    # Добавляем визуальный прогресс
    if stats.get('total', 0) > 0:
        progress_bar = UniversalUIComponents.create_progress_bar(
            current=stats.get('correct', 0),
            total=stats.get('total', 0),
            width=15
        )
        text += f"\n\n<b>Прогресс:</b>\n{progress_bar}"
    
    text += f"\n🔥 Текущая серия: {stats.get('streak', 0)}\n"
    text += f"🏆 Рекорд серии: {stats.get('max_streak', 0)}\n"
    
    if mistake_count > 0:
        text += f"\n📚 Вопросов на повторение: {mistake_count}\n"
    else:
        text += "\n👍 Отличная работа, ошибок нет!"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def send_question(message, context: ContextTypes.DEFAULT_TYPE,
                       question_data: dict, last_mode: str):
    """Отправка вопроса пользователю."""
    
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
    
    question_id = question_data.get('id')
    
    # Очищаем данные предыдущих вопросов
    logger.info(f"Clearing old question data before sending new question {question_id}")
    keys_to_remove = []
    for key in context.user_data.keys():
        if key.startswith('question_') and key != f'question_{question_id}':
            keys_to_remove.append(key)
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    
    # Сохраняем данные вопроса под его ID
    context.user_data[f'question_{question_id}'] = question_data
    context.user_data['current_question_id'] = question_id
    context.user_data['last_mode'] = last_mode
    
    # Формируем текст вопроса
    question_type = question_data.get('type', 'неизвестно')
    question_text = question_data.get('content', question_data.get('question', 'Текст вопроса отсутствует'))
    topic = question_data.get('topic', 'Без темы')
    
    # Добавляем визуальный заголовок
    fancy_header = UniversalUIComponents.create_fancy_header(
        title=f"Вопрос №{context.user_data.get('question_number', 1)}",
        subtitle=f"Тема: {topic}"
    )

    full_text = fancy_header + "\n\n" + question_text

    # Добавляем индикатор сложности если есть
    if question_data.get('difficulty'):
        difficulty_indicator = UniversalUIComponents.get_color_for_score(
            score=question_data['difficulty'],
            max_score=5
        )
        full_text += f"\n\nСложность: {difficulty_indicator}"
    
    # Добавляем информацию о номере задания если есть
    exam_number = question_data.get('exam_number')
    if exam_number:
        header = f"📝 <b>Задание №{exam_number}</b>\n"
    else:
        header = f"📝 <b>Вопрос</b>\n"
    
    # Добавляем тему
    header += f"📚 Тема: {topic}\n"
    header += f"🔤 Тип: {question_type}\n\n"
    
    full_text = header + question_text
    
    # Отправляем или редактируем сообщение
    try:
        if hasattr(message, 'edit_text'):
            await message.edit_text(full_text, parse_mode=ParseMode.HTML)
        else:
            sent_msg = await message.reply_text(full_text, parse_mode=ParseMode.HTML)
            context.user_data['question_message_id'] = sent_msg.message_id
    except Exception as e:
        logger.error(f"Error sending question: {e}")
        if hasattr(message, 'edit_text'):
            await message.edit_text("❌ Ошибка при отправке вопроса")
        else:
            await message.reply_text("❌ Ошибка при отправке вопроса")

async def send_mistake_question(message, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет вопрос из очереди ошибок."""
    mistake_queue = context.user_data.get('mistake_queue', [])
    current_index = context.user_data.get('current_mistake_index', 0)
    
    if current_index >= len(mistake_queue):
        # Все ошибки пройдены
        kb = keyboards.get_initial_choice_keyboard()
        
        if hasattr(message, 'edit_text'):
            await message.edit_text(
                "✅ Вы прошли все ошибки!\n\nВыберите режим:",
                reply_markup=kb
            )
        else:
            await message.reply_text(
                "✅ Вы прошли все ошибки!\n\nВыберите режим:",
                reply_markup=kb
            )
        return states.CHOOSING_MODE
    
    # Получаем ID вопроса
    question_id = mistake_queue[current_index]
    
    # Ищем вопрос в QUESTIONS_DICT_FLAT
    question_data = QUESTIONS_DICT_FLAT.get(question_id)
    
    if not question_data:
        logger.error(f"Question {question_id} not found in QUESTIONS_DICT_FLAT")
        # Пропускаем этот вопрос
        context.user_data['current_mistake_index'] = current_index + 1
        await send_mistake_question(message, context)
        return
    
    # Отправляем вопрос
    await send_question(message, context, question_data, "mistakes")

@safe_handler()
@validate_state_transition({
    states.CHOOSING_MODE,
    states.CHOOSING_BLOCK,
    states.CHOOSING_TOPIC,
    states.ANSWERING,
    states.CHOOSING_NEXT_ACTION,
    None,
    ConversationHandler.END
})
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    from core.plugin_loader import build_main_menu
    
    query = update.callback_query
    await query.answer()
    
    # Очищаем контекст
    context.user_data.clear()
    
    kb = build_main_menu()
    await query.edit_message_text(
        "👋 Что хотите потренировать?",
        reply_markup=kb
    )
    
    return ConversationHandler.END