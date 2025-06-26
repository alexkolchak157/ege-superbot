"""
Безопасные обработчики ответов для task19, task20, task25
с проверкой evaluator на None и fallback логикой.
"""
import logging
from typing import Optional, Dict, Any
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from core import states
from core.universal_ui import AdaptiveKeyboards, MessageFormatter
from core.ui_helpers import (
    show_extended_thinking_animation,
    get_motivational_message
)
from datetime import datetime

logger = logging.getLogger(__name__)


class SafeEvaluatorMixin:
    """Миксин для безопасной работы с evaluator."""
    
    @staticmethod
    async def safe_evaluate(
        evaluator: Any,
        user_answer: str,
        topic: Dict[str, Any],
        task_number: int,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> Dict[str, Any]:
        """
        Безопасная проверка ответа с fallback на простую логику.
        
        Returns:
            Dict с ключами:
            - success: bool
            - score: int
            - max_score: int
            - feedback: str
            - details: Dict (опционально)
        """
        user_id = update.effective_user.id
        
        # Показываем анимацию проверки
        checking_msg = await show_extended_thinking_animation(
            update.message,
            f"Проверяю ваш ответ на задание {task_number}",
            duration=60
        )
        
        try:
            # Проверяем наличие и работоспособность evaluator
            if evaluator and hasattr(evaluator, 'evaluate'):
                try:
                    # Пытаемся использовать AI evaluator
                    result = await evaluator.evaluate(
                        answer=user_answer,
                        topic=topic.get('title', ''),
                        topic_data=topic
                    )
                    
                    # Удаляем анимацию
                    await checking_msg.delete()
                    
                    return {
                        'success': True,
                        'score': result.total_score,
                        'max_score': result.max_score,
                        'feedback': result.format_feedback(),
                        'details': result.score_breakdown if hasattr(result, 'score_breakdown') else {}
                    }
                    
                except Exception as e:
                    logger.warning(f"AI evaluator failed for task {task_number}: {e}")
                    # Переходим к fallback
            
            # Fallback: простая проверка длины и ключевых слов
            logger.info(f"Using fallback evaluation for task {task_number}")
            
            score = 0
            max_score = 5
            feedback_parts = []
            
            # Базовая проверка длины
            if len(user_answer) > 100:
                score += 2
                feedback_parts.append("✅ Развернутый ответ")
            else:
                feedback_parts.append("⚠️ Ответ мог быть более развернутым")
            
            # Проверка ключевых слов (если есть)
            keywords = topic.get('keywords', [])
            if keywords:
                found_keywords = sum(1 for kw in keywords if kw.lower() in user_answer.lower())
                if found_keywords > 0:
                    score += min(3, found_keywords)
                    feedback_parts.append(f"✅ Найдено ключевых понятий: {found_keywords}")
                else:
                    feedback_parts.append("⚠️ Не найдены ключевые понятия темы")
            else:
                # Если нет ключевых слов, даем средний балл за попытку
                score += 2
                feedback_parts.append("📝 Ответ принят")
            
            # Удаляем анимацию
            await checking_msg.delete()
            
            # Формируем финальный фидбек
            feedback = (
                f"<b>Результат проверки (упрощенный режим):</b>\n\n"
                f"{''.join(f'{part}<br/>' for part in feedback_parts)}\n"
                f"<b>Итого: {score}/{max_score} баллов</b>\n\n"
                f"<i>💡 Для более точной проверки требуется подключение AI-сервиса</i>"
            )
            
            return {
                'success': True,
                'score': score,
                'max_score': max_score,
                'feedback': feedback,
                'details': {'fallback': True}
            }
            
        except Exception as e:
            logger.error(f"Error in safe_evaluate for task {task_number}: {e}")
            
            # Удаляем анимацию в случае ошибки
            try:
                await checking_msg.delete()
            except:
                pass
            
            # Возвращаем минимальный результат
            return {
                'success': False,
                'score': 0,
                'max_score': 5,
                'feedback': (
                    "❌ Произошла ошибка при проверке ответа.\n"
                    "Пожалуйста, попробуйте еще раз или обратитесь к администратору."
                ),
                'details': {'error': str(e)}
            }


async def safe_handle_answer_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Безопасный обработчик для task19."""
    logger.info(f"safe_handle_answer_task19 called for user {update.effective_user.id}")
    
    # Получаем evaluator из модуля task19
    try:
        from task19.handlers import evaluator
    except ImportError:
        logger.warning("Could not import evaluator from task19")
        evaluator = None
    
    user_answer = update.message.text
    topic = context.user_data.get('current_topic')
    
    if not topic:
        logger.error("No topic found in context")
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 К заданиям", callback_data="t19_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем анимацию проверки
    checking_msg = await show_extended_thinking_animation(
        update.message,
        "Проверяю ваш ответ на задание 19",
        duration=30
    )
    
    try:
        # Используем безопасную оценку
        result = await SafeEvaluatorMixin.safe_evaluate(
            evaluator=evaluator,
            user_answer=user_answer,
            topic=topic,
            task_number=19,
            update=update,
            context=context
        )
        
        # Удаляем анимацию
        try:
            await checking_msg.delete()
        except Exception as e:
            logger.debug(f"Could not delete checking message: {e}")
        
        # Сохраняем результат
        context.user_data.setdefault('task19_results', []).append({
            'topic': topic['title'],
            'score': result['score'],
            'max_score': result['max_score'],
            'timestamp': datetime.now().isoformat()
        })
        
        # Показываем результат
        await update.message.reply_text(
            result['feedback'],
            reply_markup=AdaptiveKeyboards.create_result_keyboard(
                score=result['score'],
                max_score=result['max_score'],
                module_code="t19"
            ),
            parse_mode=ParseMode.HTML
        )
        
        logger.info(f"Answer evaluated for user {update.effective_user.id}: {result['score']}/{result['max_score']}")
        
        return states.CHOOSING_MODE
        
    except Exception as e:
        logger.error(f"Error in safe_handle_answer_task19: {e}")
        
        # Удаляем анимацию в случае ошибки
        try:
            await checking_msg.delete()
        except:
            pass
        
        # Показываем сообщение об ошибке
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке ответа. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Попробовать снова", callback_data="t19_practice"),
                InlineKeyboardButton("📝 В меню", callback_data="t19_menu")
            ]])
        )
        
        return states.CHOOSING_MODE


async def safe_handle_answer_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Безопасный обработчик для task20."""
    
    # НОВОЕ: Проверяем активный модуль
    active_module = context.user_data.get('active_module')
    if active_module != 'task20':
        # Не наш модуль, игнорируем
        return states.CHOOSING_MODE
    # Получаем evaluator из модуля task20
    try:
        from task20.handlers import evaluator
    except ImportError:
        logger.warning("Could not import evaluator from task20")
        evaluator = None
    
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
    
    # Используем безопасную оценку
    result = await SafeEvaluatorMixin.safe_evaluate(
        evaluator=evaluator,
        user_answer=user_answer,
        topic=topic,
        task_number=20,
        update=update,
        context=context
    )
    
    # Обновляем статистику
    stats_key = f'task20_practice_{topic["id"]}'
    if stats_key not in context.user_data:
        context.user_data[stats_key] = {
            'attempts': 0,
            'total_score': 0,
            'best_score': 0
        }
    
    stats = context.user_data[stats_key]
    stats['attempts'] += 1
    stats['total_score'] += result['score']
    stats['best_score'] = max(stats['best_score'], result['score'])
    
    # Показываем результат
    await update.message.reply_text(
        result['feedback'],
        reply_markup=AdaptiveKeyboards.create_result_keyboard(
            score=result['score'],
            max_score=result['max_score'],
            module_code="t20"
        ),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def safe_handle_answer_task25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Безопасный обработчик для task25."""
    # НОВОЕ: Проверяем активный модуль
    active_module = context.user_data.get('active_module')
    if active_module != 'task25':
        # Не наш модуль, игнорируем
        return states.CHOOSING_MODE
    # Получаем evaluator из модуля task25
    try:
        from task25.handlers import evaluator
    except ImportError:
        logger.warning("Could not import evaluator from task25")
        evaluator = None
    
    user_answer = update.message.text
    topic = context.user_data.get('current_topic')
    
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 К заданиям", callback_data="t25_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Используем безопасную оценку
    result = await SafeEvaluatorMixin.safe_evaluate(
        evaluator=evaluator,
        user_answer=user_answer,
        topic=topic,
        task_number=25,
        update=update,
        context=context
    )
    
    # Обновляем прогресс пользователя
    if 'task25_progress' not in context.user_data:
        context.user_data['task25_progress'] = {}
    
    context.user_data['task25_progress'][topic['id']] = {
        'completed': True,
        'score': result['score'],
        'max_score': result['max_score'],
        'timestamp': datetime.now().isoformat()
    }
    
    # Показываем результат
    await update.message.reply_text(
        result['feedback'],
        reply_markup=AdaptiveKeyboards.create_result_keyboard(
            score=result['score'],
            max_score=result['max_score'],
            module_code="t25"
        ),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE
