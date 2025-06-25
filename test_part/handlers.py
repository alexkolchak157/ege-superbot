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
from core.state_validator import validate_state_transition, state_validator

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
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # Используем utils из локального модуля для проверки подписки
    if not await utils.check_subscription(query.from_user.id, context.bot):
        await utils.send_subscription_required(query, REQUIRED_CHANNEL)
        return ConversationHandler.END
    
    kb = keyboards.get_initial_choice_keyboard()
    await query.edit_message_text(
        "📚 <b>Тестовая часть ЕГЭ</b>\n\n"
        "Выберите режим работы:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
async def select_exam_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор режима по номеру ЕГЭ."""
    query = update.callback_query
    
    # Используем безопасную функцию для получения номеров
    all_nums = safe_cache_get_all_exam_numbers()
    
    if not all_nums:
        return states.CHOOSING_MODE
    
    kb = keyboards.get_exam_number_keyboard(all_nums)
    await query.edit_message_text(
        "Выберите номер задания ЕГЭ:",
        reply_markup=kb
    )
    context.user_data['mode'] = 'exam_num'
    return states.CHOOSING_EXAM_NUMBER

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_block_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор режима по блокам."""
    query = update.callback_query
    
    kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
    await query.edit_message_text(
        "Выберите блок тем:",
        reply_markup=kb
    )
    context.user_data['mode'] = 'block'
    return states.CHOOSING_BLOCK

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_random_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайный вопрос из всей базы."""
    query = update.callback_query
    
    # Собираем все вопросы
    all_questions = []
    for block_data in QUESTIONS_DATA.values():
        for topic_questions in block_data.values():
            all_questions.extend(topic_questions)
    
    if not all_questions:
        return states.CHOOSING_MODE
    
    await query.edit_message_text("⏳ Загружаю случайный вопрос...")
    
    # Выбираем вопрос
    question_data = await utils.choose_question(query.from_user.id, all_questions)
    if question_data:
        await send_question(query.message, context, question_data, "random_all")
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

async def check_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка ответа с прогрессом только правильных ответов."""
    user_id = update.effective_user.id
    user_answer = update.message.text.strip()
    
    # Сохраняем ID сообщения с ответом для удаления
    context.user_data['answer_message_id'] = update.message.message_id

    # Показываем анимацию ожидания проверки
    thinking_msg = await show_thinking_animation(update.message, "Проверяю ваш ответ")
    context.user_data['thinking_message_id'] = thinking_msg.message_id
    
    # Получаем ID текущего вопроса
    current_question_id = context.user_data.get('current_question_id')
    if not current_question_id:
        logger.error(f"No current_question_id for user {user_id}")
        await update.message.reply_text(
            "❌ Ошибка: не найден текущий вопрос.\n"
            "Используйте /start для начала работы."
        )
        return ConversationHandler.END
    
    # Получаем данные вопроса по его ID
    question_data = context.user_data.get(f'question_{current_question_id}')
    if not question_data:
        logger.error(f"No question data for ID {current_question_id}, user {user_id}")
        await update.message.reply_text(
            "❌ Ошибка: не найдены данные текущего вопроса.\n"
            "Используйте /start для начала работы."
        )
        return ConversationHandler.END
    
    # Извлекаем данные из question_data
    correct_answer = str(question_data.get('answer', ''))
    question_type = question_data.get('type', 'multiple_choice')
    topic = question_data.get('topic')
    question_id = question_data.get('id')
    
    # Нормализуем ответы для сравнения
    normalized_user = utils.normalize_answer(user_answer, question_type)
    normalized_correct = utils.normalize_answer(correct_answer, question_type)
    is_correct = normalized_user == normalized_correct
    
    # Логирование для отладки
    logger.info(f"User {user_id} answered question {question_id}: {is_correct}")
    
    try:
        # Обновляем БД
        await db.update_progress(user_id, topic, is_correct)
        await db.record_answered(user_id, question_id)
        
        # Обновляем дневной стрик (всегда при любом ответе)
        daily_current, daily_max = await db.update_daily_streak(user_id)
        
        # Получаем стрики ДО обновления для сравнения
        old_correct_streak = context.user_data.get('last_correct_streak', 0)
        
        # Обновляем стрик правильных ответов
        if is_correct:
            correct_current, correct_max = await db.update_correct_streak(user_id)
            # Сохраняем для следующего раза
            context.user_data['last_correct_streak'] = correct_current
            context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
            await show_streak_notification(update, context, 'correct', context.user_data['correct_streak'])
        else:
            await db.reset_correct_streak(user_id)
            correct_current = 0
            # Получаем максимальный стрик для отображения при сбросе
            streaks = await db.get_user_streaks(user_id)
            correct_max = streaks.get('max_correct', 0)
            await db.record_mistake(user_id, question_id)
            context.user_data['last_correct_streak'] = 0
            context.user_data['correct_streak'] = 0
    
    except Exception as e:
        logger.error(f"Failed to update progress for user {user_id}: {e}")
        await update.message.reply_text("Произошла ошибка при сохранении прогресса")
        return ConversationHandler.END
    
    # Получаем прогресс ТОЛЬКО ПРАВИЛЬНЫХ ответов
    progress_text = ""
    last_mode = context.user_data.get('last_mode', 'random_all')
    
    try:
        if last_mode == 'exam_num':
            exam_number = context.user_data.get('current_exam_number')
            if exam_number:
                # Получаем все вопросы этого задания
                questions_with_num = safe_cache_get_by_exam_num(exam_number)
                total_questions = len(questions_with_num)
                
                # Получаем статистику по темам для этого задания
                stats = await db.get_user_stats(user_id)
                correct_count = 0
                
                # Подсчитываем правильные ответы для вопросов этого задания
                for topic_stat, correct, total in stats:
                    # Находим вопросы этой темы в текущем задании
                    topic_questions_in_exam = [q for q in questions_with_num if q.get('topic') == topic_stat]
                    if topic_questions_in_exam:
                        # Добавляем правильные ответы по этой теме
                        correct_count += correct
                
                progress_bar = create_visual_progress(correct_count, total_questions)
                progress_text = f"✅ Решено правильно по заданию №{exam_number}: {progress_bar}"
        
        elif last_mode == 'topic':
            selected_topic = context.user_data.get('selected_topic')
            if selected_topic:
                # Получаем все вопросы темы
                questions_in_topic = safe_cache_get_by_topic(selected_topic)
                total_questions = len(questions_in_topic)
                
                # Получаем статистику по этой теме
                stats = await db.get_user_stats(user_id)
                correct_count = 0
                
                for topic_stat, correct, total in stats:
                    if topic_stat == selected_topic:
                        correct_count = correct
                        break
                
                progress_bar = create_visual_progress(correct_count, total_questions)
                topic_name = utils.TOPIC_NAMES.get(selected_topic, selected_topic)
                progress_text = f"✅ Решено правильно по теме \"{topic_name}\": {progress_bar}"
        
        elif last_mode == 'block':
            selected_block = context.user_data.get('selected_block')
            if selected_block:
                # Получаем все вопросы блока
                questions_in_block = safe_cache_get_by_block(selected_block)
                total_questions = len(questions_in_block)
                
                # Получаем статистику по всем темам блока
                stats = await db.get_user_stats(user_id)
                correct_count = 0
                
                for topic_stat, correct, total in stats:
                    # Проверяем, относится ли тема к этому блоку
                    if selected_block in QUESTIONS_DATA and topic_stat in QUESTIONS_DATA[selected_block]:
                        correct_count += correct
                
                progress_bar = create_visual_progress(correct_count, total_questions)
                progress_text = f"✅ Решено правильно по блоку \"{selected_block}\": {progress_bar}"
    
    except Exception as e:
        logger.error(f"Error calculating progress for user {user_id}: {e}")
        progress_text = ""

    motivational_phrase = ""
    try:
        motivational_phrase = get_motivational_message(correct_count, total_questions)
    except Exception:
        pass
    
    # Формируем ответ с улучшенной обратной связью
    if is_correct:
        # Случайная фраза для правильного ответа
        feedback = f"<b>{utils.get_random_correct_phrase()}</b>\n\n"
        
        # Добавляем прогресс правильных ответов
        if progress_text:
            feedback += f"{progress_text}\n\n"
        
        # Стрики
        feedback += f"🔥 <b>Стрики:</b>\n"
        feedback += f"📅 Дней подряд: {daily_current}\n"
        feedback += f"✨ Правильных подряд: {correct_current}"
        
        # Специальная фраза для достижения milestone
        milestone_phrase = utils.get_streak_milestone_phrase(correct_current)
        if milestone_phrase and correct_current > old_correct_streak:
            feedback += f"\n\n{milestone_phrase}"

        # Новый рекорд
        if correct_current > old_correct_streak and correct_current == correct_max and correct_max > 1:
            feedback += f"\n\n🎉 <b>НОВЫЙ РЕКОРД!</b>"

        if motivational_phrase:
            feedback += f"\n\n{motivational_phrase}"

    else:
        # Случайная фраза для неправильного ответа
        feedback = f"<b>{utils.get_random_incorrect_phrase()}</b>\n\n"
        feedback += f"Ваш ответ: <code>{user_answer}</code>\n"
        feedback += f"Правильный ответ: <b>{correct_answer}</b>\n\n"
        
        # Добавляем прогресс правильных ответов (не меняется при неправильном)
        if progress_text:
            feedback += f"{progress_text}\n\n"
        
        # Стрики
        feedback += f"🔥 <b>Стрики:</b>\n"
        feedback += f"📅 Дней подряд: {daily_current}\n"
        
        # При сбросе стрика показываем рекорд
        if old_correct_streak > 0:
            feedback += f"✨ Правильных подряд: 0\n"
            feedback += f"\n💔 Серия из {old_correct_streak} правильных ответов прервана!"
            if correct_max > 0:
                feedback += f"\n📈 Ваш рекорд: {correct_max}"
        else:
            feedback += f"✨ Правильных подряд: 0"

    if motivational_phrase and not is_correct:
        feedback += f"\n\n{motivational_phrase}"
    
    # Показываем кнопки "что дальше"
    has_explanation = bool(question_data.get('explanation'))
    kb = keyboards.get_next_action_keyboard(last_mode, has_explanation=has_explanation)
    
    try:
        sent_msg = await update.message.reply_text(
            feedback,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )

        # Удаляем сообщение с индикатором ожидания
        thinking_id = context.user_data.pop('thinking_message_id', None)
        if thinking_id:
            try:
                await update.message.bot.delete_message(update.message.chat_id, thinking_id)
            except Exception:
                pass
        
        # Сохраняем ID сообщения с фидбеком для удаления
        context.user_data['feedback_message_id'] = sent_msg.message_id
        
        # Сохраняем данные о правильности ответа для пояснения
        context.user_data['last_answer_correct'] = is_correct
        
        return states.CHOOSING_NEXT_ACTION
    
    except Exception as e:
        logger.error(f"Error sending feedback to user {user_id}: {e}")
        await update.message.reply_text("Произошла ошибка при отправке ответа")
        thinking_id = context.user_data.pop('thinking_message_id', None)
        if thinking_id:
            try:
                await update.message.bot.delete_message(update.message.chat_id, thinking_id)
            except Exception:
                pass
        return ConversationHandler.END

@safe_handler()
@validate_state_transition({states.CHOOSING_NEXT_ACTION, states.ANSWERING})
async def handle_next_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после ответа (ИСПРАВЛЕННАЯ ВЕРСИЯ)."""
    query = update.callback_query    
    # Удаляем сообщение "Проверяю ваш ответ..." если оно есть
    checking_msg_id = context.user_data.pop('checking_message_id', None)
    if checking_msg_id:
        try:
            await update.callback_query.message.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=checking_msg_id
            )
        except Exception as e:
            logger.debug(f"Failed to delete checking message: {e}")

    
    action = query.data
    
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
    """Отправка вопроса пользователю БЕЗ прогресс-бара."""
    
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
    
    # ВАЖНО: Очищаем данные предыдущих вопросов
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
                f"Topic={question_data.get('topic')}")
   
    
    # Добавляем информацию о блоке и теме
    if 'block' not in question_data and context.user_data.get('selected_block'):
        question_data['block'] = context.user_data['selected_block']
    if 'topic' not in question_data and context.user_data.get('selected_topic'):
        question_data['topic'] = context.user_data['selected_topic']
    
    # Сохраняем номер задания ЕГЭ для режима exam_num
    if last_mode == 'exam_num' and 'exam_number' in question_data:
        context.user_data['current_exam_number'] = question_data['exam_number']
    
    # Получаем user_id
    if hasattr(message, 'from_user'):
        user_id = message.from_user.id
    elif hasattr(message, 'chat_id'):
        user_id = message.chat_id
    else:
        user_id = message.message.chat_id
    
    # Форматируем текст вопроса БЕЗ прогресс-бара
    text = utils.format_question_text(question_data)
    
    # Отправляем сообщение
    try:
        if hasattr(message, 'edit_text'):
            # Это CallbackQuery - редактируем сообщение
            await message.edit_text(text, parse_mode=ParseMode.HTML)
            # Сохраняем ID сообщения
            context.user_data['current_question_message_id'] = message.message_id
        else:
            # Это обычное сообщение - отправляем новое
            sent_msg = await message.reply_text(text, parse_mode=ParseMode.HTML)
            # Сохраняем ID нового сообщения
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
    
    return states.ANSWERING

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
    """Отправка вопроса из списка ошибок."""
    mistake_ids = context.user_data.get('mistake_ids', [])
    current_index = context.user_data.get('current_mistake_index', 0)
    
    if current_index >= len(mistake_ids):
        # Если это CallbackQuery, используем edit_message_text
        if hasattr(message, 'edit_text'):
            await message.edit_text(
                "🎉 Вы проработали все ошибки! Отличная работа!",
                reply_markup=keyboards.get_initial_choice_keyboard()
            )
        else:
            await message.reply_text(
                "🎉 Вы проработали все ошибки! Отличная работа!",
                reply_markup=keyboards.get_initial_choice_keyboard()
            )
        return ConversationHandler.END
    
    question_id = mistake_ids[current_index]
    
    # Используем QUESTIONS_DICT_FLAT или ищем вопрос
    question_data = None
    if QUESTIONS_DICT_FLAT:
        question_data = QUESTIONS_DICT_FLAT.get(question_id)
    
    # Если не нашли в QUESTIONS_DICT_FLAT, ищем через cache или перебором
    if not question_data:
        if questions_cache:
            question_data = questions_cache.get_by_id(question_id)
        else:
            # Ищем перебором
            for block_data in QUESTIONS_DATA.values():
                for topic_questions in block_data.values():
                    for q in topic_questions:
                        if q.get('id') == question_id:
                            question_data = q
                            break
                    if question_data:
                        break
                if question_data:
                    break
    
    if not question_data:
        # Пропускаем несуществующий вопрос
        logger.warning(f"Question {question_id} not found in mistakes mode")
        # Удаляем эту ошибку из БД
        await db.delete_mistake(context.user_data.get('user_id', message.from_user.id), question_id)
        context.user_data['current_mistake_index'] = current_index + 1
        return await send_mistake_question(message, context)
    
    # Сохраняем данные для проверки ответа
    context.user_data[f'question_{question_id}'] = question_data
    context.user_data['current_question_id'] = question_id
    context.user_data['last_mode'] = 'mistakes'
    
    # Форматируем
    text = f"🔧 <b>Работа над ошибками ({current_index + 1}/{len(mistake_ids)})</b>\n\n"
    text += utils.format_question_text(question_data)
    
    # Отправляем
    if hasattr(message, 'edit_text'):
        sent_msg = await message.edit_text(text, parse_mode=ParseMode.HTML)
        context.user_data['current_question_message_id'] = message.message_id
    else:
        sent_msg = await message.reply_text(text, parse_mode=ParseMode.HTML)
        if sent_msg:
            context.user_data['current_question_message_id'] = sent_msg.message_id
    
    return states.REVIEWING_MISTAKES

@safe_handler()
@validate_state_transition({states.REVIEWING_MISTAKES})
async def handle_mistake_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа в режиме ошибок."""
    user_id = update.effective_user.id
    user_answer = update.message.text.strip()
    
    # Сохраняем ID сообщения с ответом
    context.user_data['answer_message_id'] = update.message.message_id
    
    # Получаем ID текущего вопроса
    current_question_id = context.user_data.get('current_question_id')
    if not current_question_id:
        await update.message.reply_text("❌ Ошибка: вопрос не найден")
        return states.CHOOSING_MODE
    
    # Получаем данные вопроса
    question_data = context.user_data.get(f'question_{current_question_id}')
    if not question_data:
        await update.message.reply_text("❌ Ошибка: данные вопроса не найдены")
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
    
    questions_in_block = safe_cache_get_by_block(selected_block)
    
    if not questions_in_block:
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
        return states.CHOOSING_TOPIC
    
    context.user_data['selected_topic'] = selected_topic
    
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
@validate_state_transition({states.CHOOSING_MODE})
async def select_mistakes_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в режим работы над ошибками из меню."""
    query = update.callback_query
    
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
async def detailed_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальный отчет по ошибкам."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем все ошибки пользователя
    mistakes = await get_user_mistakes(user_id)
    
    if not mistakes:
        text = "📊 <b>Детальный отчет</b>\n\nУ вас пока нет ошибок для анализа!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="test_progress")
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
        [InlineKeyboardButton("⬅️ Назад", callback_data="test_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспортирует статистику и ошибки в CSV файл."""
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer("Подготавливаю файл...")
    
    # Получаем данные
    mistakes = await get_user_mistakes(user_id)
    stats = await db.get_user_stats(user_id)
    
    # Создаем CSV в памяти
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Заголовок с информацией
    writer.writerow(['Отчет по тестовой части ЕГЭ'])
    writer.writerow([f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}'])
    writer.writerow([])
    
    # Общая статистика
    writer.writerow(['ОБЩАЯ СТАТИСТИКА'])
    writer.writerow(['Тема', 'Правильных ответов', 'Всего отвечено', 'Процент'])
    
    total_correct = 0
    total_answered = 0
    
    for topic, correct, answered in stats:
        percentage = (correct / answered * 100) if answered > 0 else 0
        writer.writerow([topic, correct, answered, f'{percentage:.1f}%'])
        total_correct += correct
        total_answered += answered
    
    writer.writerow([])
    writer.writerow(['ИТОГО', total_correct, total_answered, 
                    f'{(total_correct/total_answered*100 if total_answered > 0 else 0):.1f}%'])
    
    # Детали ошибок
    if mistakes:
        writer.writerow([])
        writer.writerow(['АНАЛИЗ ОШИБОК'])
        writer.writerow(['ID вопроса', 'Тема', 'Тип ошибки', 'Дата'])
        
        for mistake in mistakes:
            writer.writerow([
                mistake.get('question_id', 'N/A'),
                mistake.get('topic', 'Без темы'),
                mistake.get('error_type', 'Неверный ответ'),
                mistake.get('timestamp', 'N/A')
            ])
    
    # Готовим файл для отправки
    output.seek(0)
    bio = io.BytesIO(output.getvalue().encode('utf-8-sig'))  # UTF-8 with BOM для Excel
    bio.name = f'ege_test_report_{user_id}_{datetime.now().strftime("%Y%m%d")}.csv'
    
    # Отправляем файл
    await query.message.reply_document(
        document=bio,
        caption="📊 Ваш отчет по тестовой части ЕГЭ\n\n"
                "Файл можно открыть в Excel или Google Sheets",
        filename=bio.name
    )
    
    # Возвращаемся в меню прогресса
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="test_progress")
    ]])
    
    await query.message.reply_text(
        "✅ Отчет успешно экспортирован!",
        reply_markup=kb
    )
    
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
@validate_state_transition({states.CHOOSING_MODE})
async def select_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в режим работы над ошибками."""
    query = update.callback_query
    
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
