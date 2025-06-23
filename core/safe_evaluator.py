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
                        'feedback': _format_ai_feedback(result, topic, task_number),
                        'details': {
                            'criteria_scores': result.criteria_scores,
                            'suggestions': result.suggestions,
                            'factual_errors': result.factual_errors
                        }
                    }
                    
                except Exception as e:
                    logger.error(f"AI evaluation failed for user {user_id}: {e}")
                    # Продолжаем с fallback логикой
            
            # Fallback: простая проверка без AI
            logger.warning(f"Using fallback evaluation for task {task_number} (evaluator: {evaluator})")
            
            # Удаляем анимацию
            await checking_msg.delete()
            
            # Простая логика оценки в зависимости от задания
            if task_number == 19:
                score = _simple_task19_evaluation(user_answer)
                max_score = 3
            elif task_number == 20:
                score = _simple_task20_evaluation(user_answer)
                max_score = 3
            elif task_number == 25:
                score = _simple_task25_evaluation(user_answer)
                max_score = 6
            else:
                score = 1
                max_score = 3
            
            feedback = _format_simple_feedback(
                score=score,
                max_score=max_score,
                topic=topic,
                task_number=task_number,
                answer_analysis=_analyze_answer_structure(user_answer, task_number)
            )
            
            return {
                'success': True,
                'score': score,
                'max_score': max_score,
                'feedback': feedback,
                'details': {}
            }
            
        except Exception as e:
            logger.exception(f"Critical error in evaluation: {e}")
            
            # Удаляем анимацию если еще не удалена
            try:
                await checking_msg.delete()
            except:
                pass
            
            return {
                'success': False,
                'score': 0,
                'max_score': 3,
                'feedback': "❌ Произошла ошибка при проверке. Попробуйте еще раз.",
                'details': {}
            }


def _simple_task19_evaluation(answer: str) -> int:
    """Простая оценка для задания 19 (примеры)."""
    lines = [line.strip() for line in answer.split('\n') if line.strip()]
    
    # Ищем нумерованные примеры
    examples_count = 0
    for line in lines:
        if any(line.startswith(f"{i})") or line.startswith(f"{i}.") for i in range(1, 10)):
            examples_count += 1
    
    # Если нет явной нумерации, считаем параграфы
    if examples_count == 0:
        paragraphs = answer.split('\n\n')
        examples_count = len([p for p in paragraphs if len(p.strip()) > 20])
    
    # Оценка: 1 балл за каждый пример, максимум 3
    score = min(examples_count, 3)
    
    # Штраф за избыточность
    if examples_count > 3:
        score = 0  # Согласно критериям ЕГЭ
    
    return score


def _simple_task20_evaluation(answer: str) -> int:
    """Простая оценка для задания 20 (суждения)."""
    lines = [line.strip() for line in answer.split('\n') if line.strip()]
    
    # Ищем суждения
    judgments_count = 0
    for line in lines:
        # Суждение обычно содержит обобщение и объяснение
        if len(line) > 30 and any(word in line.lower() for word in 
            ['поскольку', 'так как', 'потому что', 'следовательно', 'поэтому']):
            judgments_count += 1
        elif any(line.startswith(f"{i})") or line.startswith(f"{i}.") for i in range(1, 10)):
            if len(line) > 20:
                judgments_count += 1
    
    # Альтернатива: считаем параграфы
    if judgments_count == 0:
        paragraphs = answer.split('\n\n')
        judgments_count = len([p for p in paragraphs if len(p.strip()) > 30])
    
    score = min(judgments_count, 3)
    if judgments_count > 3:
        score = 0
    
    return score


def _simple_task25_evaluation(answer: str) -> int:
    """Простая оценка для задания 25 (обоснование + примеры)."""
    # Разделяем на части
    parts = answer.split('\n\n')
    
    score = 0
    
    # Проверяем наличие трех частей
    if len(parts) >= 3:
        # Часть 1: Обоснование (до 2 баллов)
        if len(parts[0]) > 50:  # Минимальная длина для обоснования
            score += 1
            if any(word in parts[0].lower() for word in 
                   ['следовательно', 'таким образом', 'поэтому', 'так как']):
                score += 1
        
        # Часть 2: Ответ на вопрос (1 балл)
        if len(parts[1]) > 10:
            score += 1
        
        # Часть 3: Примеры (до 3 баллов)
        examples = 0
        for i in range(2, min(len(parts), 5)):  # Проверяем до 3 примеров
            if len(parts[i]) > 30:
                examples += 1
        
        score += min(examples, 3)
    
    return min(score, 6)


def _analyze_answer_structure(answer: str, task_number: int) -> Dict[str, Any]:
    """Анализ структуры ответа."""
    lines = [line.strip() for line in answer.split('\n') if line.strip()]
    paragraphs = answer.split('\n\n')
    
    analysis = {
        'total_lines': len(lines),
        'total_paragraphs': len(paragraphs),
        'total_words': len(answer.split()),
        'has_numbering': any(
            any(line.startswith(f"{i})") or line.startswith(f"{i}.") 
                for i in range(1, 10))
            for line in lines
        )
    }
    
    if task_number == 19:
        analysis['estimated_examples'] = _count_examples(lines, paragraphs)
    elif task_number == 20:
        analysis['estimated_judgments'] = _count_judgments(lines, paragraphs)
    elif task_number == 25:
        analysis['has_three_parts'] = len(paragraphs) >= 3
        
    return analysis


def _count_examples(lines: list, paragraphs: list) -> int:
    """Подсчет примеров в ответе."""
    count = 0
    
    # Считаем нумерованные строки
    for line in lines:
        if any(line.startswith(f"{i})") or line.startswith(f"{i}.") for i in range(1, 10)):
            count += 1
    
    # Если нет нумерации, считаем существенные параграфы
    if count == 0:
        count = len([p for p in paragraphs if len(p.strip()) > 50])
    
    return count


def _count_judgments(lines: list, paragraphs: list) -> int:
    """Подсчет суждений в ответе."""
    count = 0
    
    for line in lines:
        # Признаки суждения: обобщение, причинно-следственные связи
        if len(line) > 30 and any(marker in line.lower() for marker in [
            'следовательно', 'таким образом', 'поэтому', 'так как',
            'поскольку', 'в результате', 'это приводит', 'это означает'
        ]):
            count += 1
    
    return min(count, 5)  # Ограничиваем разумным числом


def _format_ai_feedback(result: Any, topic: Dict, task_number: int) -> str:
    """Форматирование обратной связи от AI."""
    feedback = MessageFormatter.format_result_message(
        score=result.total_score,
        max_score=result.max_score,
        topic=topic['title']
    )
    
    # Добавляем детальный анализ
    feedback += "\n\n<b>📋 Детальный анализ:</b>\n"
    
    for criterion in result.criteria_scores:
        status = "✅" if criterion.met else "❌"
        feedback += f"\n{status} <b>{criterion.name}:</b> {criterion.score}/{criterion.max_score}"
        if criterion.feedback:
            feedback += f"\n   └ <i>{criterion.feedback}</i>"
    
    # Рекомендации
    if result.suggestions:
        feedback += "\n\n<b>💡 Рекомендации:</b>"
        for suggestion in result.suggestions[:3]:
            feedback += f"\n• {suggestion}"
    
    # Фактические ошибки
    if result.factual_errors:
        feedback += "\n\n<b>⚠️ Обратите внимание:</b>"
        for error in result.factual_errors[:2]:
            feedback += f"\n• {error}"
    
    return feedback


def _format_simple_feedback(
    score: int, 
    max_score: int, 
    topic: Dict,
    task_number: int,
    answer_analysis: Dict
) -> str:
    """Форматирование обратной связи для простой проверки."""
    
    feedback = f"📊 <b>Результаты проверки (упрощенная)</b>\n\n"
    feedback += f"<b>Тема:</b> {topic['title']}\n"
    feedback += f"<b>Предварительная оценка:</b> {score} из {max_score}\n\n"
    
    # Анализ структуры
    feedback += "<b>📝 Анализ ответа:</b>\n"
    
    if task_number == 19:
        examples = answer_analysis.get('estimated_examples', 0)
        feedback += f"• Примеров обнаружено: {examples}\n"
        
        if examples == 3:
            feedback += "✅ Количество примеров соответствует требованиям\n"
        elif examples < 3:
            feedback += "❌ Необходимо привести 3 примера\n"
        else:
            feedback += "❌ Приведено больше 3 примеров (0 баллов по критериям)\n"
            
    elif task_number == 20:
        judgments = answer_analysis.get('estimated_judgments', 0)
        feedback += f"• Суждений обнаружено: {judgments}\n"
        
        if judgments >= 3:
            feedback += "✅ Достаточное количество суждений\n"
        else:
            feedback += "❌ Необходимо сформулировать 3 суждения\n"
            
    elif task_number == 25:
        if answer_analysis.get('has_three_parts'):
            feedback += "✅ Ответ содержит три части\n"
        else:
            feedback += "❌ Ответ должен содержать: обоснование, ответ и примеры\n"
    
    # Общие метрики
    feedback += f"\n• Всего слов: {answer_analysis['total_words']}"
    feedback += f"\n• Абзацев: {answer_analysis['total_paragraphs']}"
    
    if answer_analysis.get('has_numbering'):
        feedback += "\n• ✅ Использована нумерация"
    
    # Важное предупреждение
    feedback += "\n\n⚠️ <b>Внимание:</b>"
    feedback += "\n<i>Это упрощенная автоматическая проверка.</i>"
    feedback += "\n<i>Для точной оценки требуется проверка экспертом.</i>"
    
    # AI недоступен
    feedback += "\n\n🤖 <i>AI-проверка временно недоступна (fallback)</i>"
    
    # Мотивация
    motivation = get_motivational_message(score, max_score)
    feedback += f"\n\n💬 {motivation}"
    
    return feedback


# Готовые функции для использования в handlers

async def safe_handle_answer_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Безопасный обработчик для task19."""
    from . import evaluator  # Локальный импорт
    
    user_answer = update.message.text
    topic = context.user_data.get('current_topic')
    
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 К заданиям", callback_data="t19_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Используем безопасную оценку
    result = await SafeEvaluatorMixin.safe_evaluate(
        evaluator=evaluator,
        user_answer=user_answer,
        topic=topic,
        task_number=19,
        update=update,
        context=context
    )
    
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
    
    return states.CHOOSING_MODE


async def safe_handle_answer_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Безопасный обработчик для task20."""
    from . import evaluator  # Локальный импорт
    
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
    from . import evaluator  # Локальный импорт
    
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
    
    # Обновляем статистику
    stats = context.user_data.setdefault('practice_stats', {})
    topic_stats = stats.setdefault(str(topic['id']), {
        'attempts': 0,
        'total_score': 0,
        'best_score': 0,
        'avg_score': 0
    })
    
    topic_stats['attempts'] += 1
    topic_stats['total_score'] += result['score']
    topic_stats['best_score'] = max(topic_stats['best_score'], result['score'])
    topic_stats['avg_score'] = topic_stats['total_score'] / topic_stats['attempts']
    
    # Показываем результат
    await update.message.reply_text(
        result['feedback'],
        reply_markup=AdaptiveKeyboards.create_result_keyboard(
            score=result['score'],
            max_score=result['max_score'],
            module_code="t25",
            show_example=True  # Показываем кнопку эталонного ответа
        ),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


# Для использования в существующем коде
from datetime import datetime