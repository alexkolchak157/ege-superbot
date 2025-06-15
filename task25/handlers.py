# plugins/task25/handlers.py

import logging
from typing import Dict, Any, Optional
from telegram import Update
from telegram.ext import ContextTypes

from .evaluator import Task25Evaluator
from .plugin import Task25Plugin

logger = logging.getLogger(__name__)

class Task25Handler:
    """Обработчик для задания 25 ЕГЭ по обществознанию"""
    
    def __init__(self, evaluator: Task25Evaluator, plugin: Task25Plugin):
        self.evaluator = evaluator
        self.plugin = plugin
        
    async def handle_task_submission(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        task_data: Dict[str, Any],
        student_answer: str
    ) -> str:
        """Обрабатывает отправку ответа на задание 25"""
        try:
            user_id = update.effective_user.id
            logger.info(f"Пользователь {user_id} отправил ответ на задание 25")
            
            # Валидация ответа
            if not student_answer or len(student_answer.strip()) < 50:
                return "❌ Ответ слишком короткий. Задание 25 требует развёрнутого ответа с обоснованием, ответом на вопрос и примерами."
            
            if len(student_answer) > 5000:
                return "❌ Ответ слишком длинный. Пожалуйста, сократите ответ до 5000 символов."
            
            # Проверка наличия текста задания
            task_text = task_data.get('text', '')
            if not task_text:
                logger.error(f"Отсутствует текст задания для task_id: {task_data.get('id')}")
                return "❌ Ошибка: не найден текст задания. Попробуйте выбрать задание заново."
            
            # Отправляем сообщение о начале проверки
            processing_msg = await update.message.reply_text(
                "⏳ Проверяю ваш ответ. Это может занять несколько секунд..."
            )
            
            # Выполняем оценку через YandexGPT
            evaluation = await self.evaluator.evaluate_answer(
                task_text=task_text,
                student_answer=student_answer,
                task_id=task_data.get('id', 'unknown')
            )
            
            # Удаляем сообщение о проверке
            await processing_msg.delete()
            
            # Форматируем и возвращаем результат
            if evaluation.get("success"):
                # Сохраняем результат в контексте для статистики
                await self._save_result(context, user_id, task_data, evaluation)
                return self.plugin.format_feedback(evaluation)
            else:
                error_msg = evaluation.get("error", "Неизвестная ошибка")
                logger.error(f"Ошибка при оценке ответа: {error_msg}")
                return f"❌ Произошла ошибка при проверке: {error_msg}"
                
        except Exception as e:
            logger.error(f"Ошибка в handle_task_submission: {e}", exc_info=True)
            return "❌ Произошла неожиданная ошибка. Пожалуйста, попробуйте ещё раз."
    
    async def _save_result(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        task_data: Dict[str, Any],
        evaluation: Dict[str, Any]
    ):
        """Сохраняет результат проверки для статистики"""
        try:
            # Инициализируем хранилище результатов, если его нет
            if 'task_results' not in context.user_data:
                context.user_data['task_results'] = {}
            
            if 'task25' not in context.user_data['task_results']:
                context.user_data['task_results']['task25'] = []
            
            # Сохраняем результат
            result = {
                'task_id': task_data.get('id'),
                'task_text': task_data.get('text', '')[:100] + '...',  # Сохраняем начало задания
                'scores': evaluation.get('scores', {}),
                'total_score': evaluation.get('total_score', 0),
                'max_score': self.plugin.max_score,
                'timestamp': context.application.bot_data.get('current_time', None)
            }
            
            context.user_data['task_results']['task25'].append(result)
            
            # Ограничиваем количество сохранённых результатов
            if len(context.user_data['task_results']['task25']) > 50:
                context.user_data['task_results']['task25'].pop(0)
                
        except Exception as e:
            logger.error(f"Ошибка при сохранении результата: {e}")
    
    def get_task_preview(self, task_data: Dict[str, Any]) -> str:
        """Возвращает превью задания для отображения пользователю"""
        task_text = task_data.get('text', 'Текст задания отсутствует')
        task_id = task_data.get('id', 'unknown')
        
        # Ограничиваем длину превью
        if len(task_text) > 500:
            task_text = task_text[:500] + "..."
            
        return (
            f"📝 **Задание 25** (ID: {task_id})\n\n"
            f"{task_text}\n\n"
            f"💡 Требования к ответу:\n"
            f"1) Обоснование (несколько распространённых предложений)\n"
            f"2) Ответ на вопрос (отдельным пунктом)\n"
            f"3) Примеры (развёрнутые, для каждого названного объекта)\n\n"
            f"Максимальный балл: {self.plugin.max_score}"
        )