"""AI-проверка для задания 25 через YandexGPT."""

import logging
import os
import json
from enum import Enum
from typing import Dict, List, Any, Optional
from core.types import (
    UserID,
    TaskType,
    EvaluationResult,
    CallbackData,
    TaskRequirements,
)

logger = logging.getLogger(__name__)

# Безопасный импорт
try:
    from core.ai_evaluator import (
        BaseAIEvaluator,
    )
    # ВАЖНО: Импортируем YandexGPTModel из core.ai_service
    from core.ai_service import YandexGPTService, YandexGPTConfig, YandexGPTModel
    AI_EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI evaluator components not available: {e}")
    AI_EVALUATOR_AVAILABLE = False

    # Заглушки для работы без AI

    class BaseAIEvaluator:
        def __init__(self, requirements: TaskRequirements):
            self.requirements = requirements
    
    class YandexGPTService:
        pass
    
    class YandexGPTConfig:
        pass
    
    # Заглушка для Enum когда AI недоступен
    from enum import Enum
    class YandexGPTModel(Enum):
        LITE = "yandexgpt-lite"
        PRO = "yandexgpt"


class Task25EvaluationResult(EvaluationResult if AI_EVALUATOR_AVAILABLE else object):
    """Расширенный результат оценки для задания 25."""

    def format_feedback(self) -> str:
        """Форматирует результат для отображения пользователю."""
        text = f"📊 <b>Результаты проверки</b>\n\n"

        # Баллы по критериям
        text += "<b>Баллы по критериям:</b>\n"

        # Используем ключи из scores, которые могут быть k1_score, k2_score, k3_score или К1, К2, К3
        scores = self.scores if hasattr(self, 'scores') and self.scores else {}

        # Проверяем разные форматы ключей
        k1_score = scores.get('k1_score', scores.get('К1', 0))
        k2_score = scores.get('k2_score', scores.get('К2', 0))
        k3_score = scores.get('k3_score', scores.get('К3', 0))

        text += f"К1 (Обоснование): {k1_score}/2\n"
        text += f"К2 (Ответ): {k2_score}/1\n"
        text += f"К3 (Примеры): {k3_score}/3\n"

        # Итоговый балл
        text += f"\n<b>Итого: {self.total_score}/{self.max_score} баллов</b>\n\n"

        # Основная обратная связь
        if self.feedback:
            text += f"{self.feedback}\n"

        # Детальный анализ если есть
        if self.detailed_analysis:
            text += "\n<b>Детальный анализ:</b>\n"

            # Комментарии по критериям
            if 'k1_comment' in self.detailed_analysis:
                text += f"\n<b>Обоснование:</b> {self.detailed_analysis['k1_comment']}\n"

            if 'k2_comment' in self.detailed_analysis:
                text += f"\n<b>Ответ:</b> {self.detailed_analysis['k2_comment']}\n"

            if 'k3_comment' in self.detailed_analysis:
                text += f"\n<b>Примеры:</b> {self.detailed_analysis['k3_comment']}\n"

                # Найденные примеры
                if 'k3_examples_found' in self.detailed_analysis:
                    examples = self.detailed_analysis['k3_examples_found']
                    if examples and isinstance(examples, list):
                        text += "\nНайденные примеры:\n"
                        for i, ex in enumerate(examples[:3], 1):
                            text += f"{i}. {ex}\n"

        # Рекомендации
        if self.suggestions:
            text += "\n💡 <b>Рекомендации:</b>\n"
            for suggestion in self.suggestions:
                text += f"• {suggestion}\n"

        # Фактические ошибки
        if self.factual_errors:
            text += "\n⚠️ <b>Обратите внимание:</b>\n"
            for error in self.factual_errors:
                if isinstance(error, dict):
                    text += f"• {error.get('error', error)}"
                    if 'correction' in error:
                        text += f" → {error['correction']}"
                    text += "\n"
                else:
                    text += f"• {error}\n"

        return text

class StrictnessLevel(Enum):
    """Уровни строгости проверки."""
    LENIENT = "Мягкий"
    STANDARD = "Стандартный" 
    STRICT = "Строгий"
    EXPERT = "Экспертный"



class Task25AIEvaluator(BaseAIEvaluator if AI_EVALUATOR_AVAILABLE else object):
    """AI-проверщик для задания 25 с настраиваемой строгостью."""
    
    def __init__(self, strictness: StrictnessLevel = StrictnessLevel.STANDARD):
        self.strictness = strictness
        
        # Требования к заданию 25
        requirements = TaskRequirements(
            task_number=25,
            task_name="Развёрнутый ответ",
            max_score=6,
            criteria=[
                {
                    "code": "К1",
                    "name": "Обоснование",
                    "max_score": 2,
                    "description": "Приведено корректное обоснование с опорой на теорию"
                },
                {
                    "code": "К2", 
                    "name": "Ответ на вопрос",
                    "max_score": 1,
                    "description": "Дан правильный ответ на поставленный вопрос"
                },
                {
                    "code": "К3",
                    "name": "Примеры",
                    "max_score": 3,
                    "description": "Приведены три развёрнутых примера (по 1 баллу за каждый)"
                }
            ],
            description="Обоснуйте, ответьте и приведите примеры"
        )
        
        if AI_EVALUATOR_AVAILABLE:
            super().__init__(requirements)
            self._init_ai_service()
        else:
            self.requirements = requirements
            self.ai_service = None
    
    def _init_ai_service(self):
        """Инициализация AI-сервиса."""
        if not AI_EVALUATOR_AVAILABLE:
            return

        try:
            api_key = os.getenv("YANDEX_GPT_API_KEY")
            folder_id = os.getenv("YANDEX_GPT_FOLDER_ID")

            if not api_key or not folder_id:
                logger.error(
                    "YANDEX_GPT_API_KEY и YANDEX_GPT_FOLDER_ID должны быть установлены"
                )
                self.ai_service = None
                return

            config = YandexGPTConfig(
                api_key=api_key,
                folder_id=folder_id,
                model=YandexGPTModel.PRO,  # Это Enum, не строка!
                temperature=self._get_temperature(),
                max_tokens=3000,
            )

            self.ai_service = YandexGPTService(config)
            logger.info(
                f"Task25 AI service initialized with {self.strictness.value} strictness"
            )

        except Exception as e:
            logger.error(f"Failed to initialize AI service: {e}")
            self.ai_service = None
    
    def get_temperature(self) -> float:
        """Возвращает температуру для AI в зависимости от строгости."""
        temps = {
            StrictnessLevel.LENIENT: 0.3,
            StrictnessLevel.STANDARD: 0.2,
            StrictnessLevel.STRICT: 0.1,
            StrictnessLevel.EXPERT: 0.05
        }
        return temps.get(self.strictness, 0.2)

    def _get_temperature(self) -> float:
        """Алиас для обратной совместимости."""
        return self.get_temperature()
    
    def get_system_prompt(self, mode='full') -> str:
        """Системный промпт для проверки задания 25."""
        
        if mode == 'parts':
            # Промпт для поэтапной проверки
            base_prompt = """Ты - эксперт ЕГЭ по обществознанию, проверяющий отдельную часть задания 25.

    ВАЖНО: Сейчас проверяется ТОЛЬКО ОДНА ЧАСТЬ задания, не весь ответ.

    При проверке части К1 (обоснование):
    - 2 балла: развёрнутое обоснование с теорией, несколько предложений
    - 1 балл: краткое обоснование или есть неточности
    - 0 баллов: обоснование отсутствует или неверное

    При проверке части К2 (ответ на вопрос):
    - 1 балл: дан правильный и полный ответ
    - 0 баллов: ответ неверный или отсутствует

    При проверке части К3 (примеры):
    - Оцени каждый пример отдельно (0-1 балл)
    - Максимум 3 балла за три корректных примера
    - Пример должен быть конкретным и развёрнутым
    """
        else:
            # Стандартный промпт для полного ответа
            base_prompt = """Ты - эксперт ЕГЭ по обществознанию, проверяющий задание 25.

    КРИТЕРИИ ОЦЕНИВАНИЯ:

    К1 - Обоснование (0-2 балла):
    - 2 балла: развёрнутое обоснование с опорой на теорию, несколько связанных предложений
    - 1 балл: краткое обоснование или есть неточности
    - 0 баллов: обоснование отсутствует или неверное

    К2 - Ответ на вопрос (0-1 балл):
    - 1 балл: дан правильный и полный ответ
    - 0 баллов: ответ неверный или отсутствует

    К3 - Примеры (0-3 балла):
    - По 1 баллу за каждый корректный развёрнутый пример (максимум 3)
    - Пример должен быть конкретным, с деталями
    - Примеры должны иллюстрировать разные аспекты

    ВАЖНО:
    - Учитывай российский контекст
    - Проверяй фактическую точность
    - Примеры должны быть из жизни РФ (если применимо)
    """
        
        # Дополнения в зависимости от строгости
        if self.strictness == StrictnessLevel.LENIENT:
            base_prompt += "\nБудь МЯГКИМ в оценке. Засчитывай частично правильные ответы."
        elif self.strictness == StrictnessLevel.STRICT:
            base_prompt += "\nПрименяй СТРОГИЕ критерии ФИПИ. Требуй полного соответствия."
        elif self.strictness == StrictnessLevel.EXPERT:
            base_prompt += "\nМАКСИМАЛЬНАЯ строгость. Любые неточности снижают балл."
        
        return base_prompt
    
    async def evaluate(
        self, 
        answer: str, 
        topic: Dict[str, Any],
        user_id: Optional[int] = None
    ) -> EvaluationResult:
        """Оценивает ответ на задание 25."""
        
        if not self.ai_service:
            return self._get_fallback_result()
        
        try:
            # Формируем промпт для оценки
            eval_prompt = self._build_evaluation_prompt(answer, topic)
            
            # Используем async with для ai_service
            async with self.ai_service as service:
                result = await service.get_completion(
                    prompt=eval_prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.get_temperature()
                )
            
            # Проверяем успешность
            if not result["success"]:
                logger.error(f"AI service error: {result.get('error', 'Unknown error')}")
                return self._get_fallback_result()
            
            response = result["text"]
            
            # Парсим результат
            parsed_result = self._parse_ai_response(response)
            
            # Валидируем и корректируем оценки
            validated_result = self._validate_scores(parsed_result)
            
            # Формируем итоговый результат
            return self._create_evaluation_result(validated_result, topic)
            
        except Exception as e:
            logger.error(f"Error during AI evaluation: {e}", exc_info=True)
            return self._get_fallback_result()
    
    def _build_evaluation_prompt(self, answer: str, topic: Dict) -> str:
        """Строит промпт для оценки ответа."""
        task_text = topic.get('task_text', '')
        
        # Разбираем части задания если они есть
        parts = topic.get('parts', {})
        part1 = parts.get('part1', '')
        part2 = parts.get('part2', '')
        part3 = parts.get('part3', '')
        
        prompt = f"""Оцени ответ ученика на задание 25.

ЗАДАНИЕ:
{task_text}

Части задания:
1) {part1}
2) {part2}
3) {part3}

ОТВЕТ УЧЕНИКА:
{answer}

Оцени каждую часть согласно критериям и верни результат в формате JSON:
{{
    "k1_score": 0-2,
    "k1_comment": "комментарий по обоснованию",
    "k2_score": 0-1,
    "k2_comment": "комментарий по ответу на вопрос",
    "k3_score": 0-3,
    "k3_comment": "комментарий по примерам",
    "k3_examples_found": ["пример 1", "пример 2", "пример 3"],
    "total_score": 0-6,
    "general_feedback": "общий комментарий",
    "suggestions": ["совет 1", "совет 2"],
    "factual_errors": ["ошибка 1", "ошибка 2"]
}}"""
        
        return prompt
    
    def _parse_ai_response(self, response: str) -> Dict:
        """Парсит ответ AI."""
        try:
            # Пытаемся найти JSON в ответе
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                # Если JSON не найден, пытаемся распарсить текст
                return self._parse_text_response(response)
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}")
            return {}
    
    def _validate_scores(self, result: Dict) -> Dict:
        """Валидирует и корректирует оценки."""
        validated = result.copy()
        
        # Проверяем К1 (0-2)
        k1 = validated.get('k1_score', 0)
        validated['k1_score'] = max(0, min(2, int(k1)))
        
        # Проверяем К2 (0-1)
        k2 = validated.get('k2_score', 0)
        validated['k2_score'] = max(0, min(1, int(k2)))
        
        # Проверяем К3 (0-3)
        k3 = validated.get('k3_score', 0)
        validated['k3_score'] = max(0, min(3, int(k3)))
        
        # Пересчитываем общий балл
        validated['total_score'] = (
            validated['k1_score'] + 
            validated['k2_score'] + 
            validated['k3_score']
        )
        
        return validated
    
    def _create_evaluation_result(self, result: Dict, topic: Dict) -> Task25EvaluationResult:
        """Создаёт итоговый результат оценки с поддержкой format_feedback."""
        # Извлекаем баллы
        scores = {
            'k1_score': result.get('k1_score', 0),
            'k2_score': result.get('k2_score', 0),
            'k3_score': result.get('k3_score', 0)
        }
        
        total_score = result.get('total_score', sum(scores.values()))
        
        # Формируем основную обратную связь
        if total_score >= 5:
            feedback = "🎉 Отличная работа! Ответ соответствует всем критериям."
        elif total_score >= 3:
            feedback = "👍 Хорошо! Есть небольшие недочёты."
        else:
            feedback = "📝 Нужно доработать ответ. Изучите рекомендации."
        
        # Добавляем общий комментарий если есть
        if result.get('general_feedback'):
            feedback = result['general_feedback']
        
        # Создаём детальный анализ
        detailed_analysis = {
            'k1_comment': result.get('k1_comment', ''),
            'k2_comment': result.get('k2_comment', ''),
            'k3_comment': result.get('k3_comment', ''),
            'k3_examples_found': result.get('k3_examples_found', [])
        }
        
        # Создаем расширенный результат
        eval_result = Task25EvaluationResult(
            criteria_scores=scores,
            total_score=total_score,
            max_score=6,
            feedback=feedback,
            detailed_feedback=detailed_analysis,  # Изменено: detailed_analysis -> detailed_feedback
            suggestions=result.get('suggestions', []),
            factual_errors=result.get('factual_errors', [])
        )
        
        return eval_result
    
    def _get_fallback_result(self) -> EvaluationResult:
        """Возвращает базовый результат при ошибке AI."""
        return EvaluationResult(
            criteria_scores={'k1_score': 0, 'k2_score': 0, 'k3_score': 0},
            total_score=0,
            max_score=6,
            feedback="⚠️ Не удалось выполнить автоматическую проверку. Обратитесь к преподавателю.",
            detailed_feedback=None,  # Изменено: detailed_analysis -> detailed_feedback
            suggestions=["Попробуйте отправить ответ позже"],
            factual_errors=None
        )

    def _parse_text_response(self, response: str) -> Dict:
        """Парсит текстовый ответ AI если JSON не удался."""
        result = {
            'k1_score': 0,
            'k2_score': 0,
            'k3_score': 0,
            'total_score': 0,
            'general_feedback': '',
            'k1_comment': '',
            'k2_comment': '',
            'k3_comment': '',
            'k3_examples_found': [],
            'suggestions': [],
            'factual_errors': []
        }
        
        try:
            # Пытаемся найти баллы по паттернам
            import re
            
            # К1 (0-2 балла)
            k1_match = re.search(r'К1.*?(\d+)\s*балл', response, re.IGNORECASE)
            if k1_match:
                result['k1_score'] = min(2, int(k1_match.group(1)))
            
            # К2 (0-1 балл)
            k2_match = re.search(r'К2.*?(\d+)\s*балл', response, re.IGNORECASE)
            if k2_match:
                result['k2_score'] = min(1, int(k2_match.group(1)))
            
            # К3 (0-3 балла)
            k3_match = re.search(r'К3.*?(\d+)\s*балл', response, re.IGNORECASE)
            if k3_match:
                result['k3_score'] = min(3, int(k3_match.group(1)))
            
            # Общий балл
            total_match = re.search(r'(?:Итог|Общ|Всего).*?(\d+).*?балл', response, re.IGNORECASE)
            if total_match:
                result['total_score'] = int(total_match.group(1))
            else:
                result['total_score'] = result['k1_score'] + result['k2_score'] + result['k3_score']
            
            # Извлекаем комментарии
            # Разбиваем ответ на секции
            lines = response.split('\n')
            current_section = None
            
            for line in lines:
                line = line.strip()
                
                # Определяем секцию
                if re.search(r'К1|обоснован', line, re.IGNORECASE):
                    current_section = 'k1'
                elif re.search(r'К2|ответ', line, re.IGNORECASE):
                    current_section = 'k2'
                elif re.search(r'К3|пример', line, re.IGNORECASE):
                    current_section = 'k3'
                elif re.search(r'рекоменд|совет', line, re.IGNORECASE):
                    current_section = 'suggestions'
                elif re.search(r'ошибк|неточност', line, re.IGNORECASE):
                    current_section = 'errors'
                
                # Добавляем контент в соответствующую секцию
                if current_section == 'k1' and len(line) > 10:
                    result['k1_comment'] += line + ' '
                elif current_section == 'k2' and len(line) > 10:
                    result['k2_comment'] += line + ' '
                elif current_section == 'k3' and len(line) > 10:
                    result['k3_comment'] += line + ' '
                elif current_section == 'suggestions' and line.startswith(('•', '-', '*')):
                    result['suggestions'].append(line.lstrip('•-* '))
                elif current_section == 'errors' and line.startswith(('•', '-', '*')):
                    result['factual_errors'].append(line.lstrip('•-* '))
            
            # Общий фидбек
            result['general_feedback'] = f"Ваш ответ оценён на {result['total_score']} из 6 баллов."
            
        except Exception as e:
            logger.error(f"Error parsing text response: {e}")
            # Возвращаем хотя бы что-то
            result['general_feedback'] = "Ответ обработан, но детальный анализ недоступен."
        
        return result
        
def format_evaluation_feedback(result: EvaluationResult, topic: Dict = None) -> str:
    """
    Форматирует результат оценки для отображения пользователю.
    
    Args:
        result: Результат оценки
        topic: Информация о теме (опционально)
        
    Returns:
        Отформатированный текст для отображения
    """
    # Если у результата есть метод format_feedback, используем его
    if hasattr(result, 'format_feedback'):
        return result.format_feedback()
    
    # Иначе форматируем вручную
    text = f"📊 <b>Результаты проверки</b>\n\n"
    
    if topic:
        text += f"<b>Тема:</b> {topic.get('title', 'Не указана')}\n"
        text += f"{'─' * 30}\n\n"
    
    # Баллы по критериям
    if result.scores:
        text += "<b>Баллы по критериям:</b>\n"
        
        # Проверяем разные форматы ключей
        k1_score = result.scores.get('k1_score', result.scores.get('К1', 0))
        k2_score = result.scores.get('k2_score', result.scores.get('К2', 0))
        k3_score = result.scores.get('k3_score', result.scores.get('К3', 0))
        
        text += f"К1 (Обоснование): {k1_score}/2\n"
        text += f"К2 (Ответ): {k2_score}/1\n"
        text += f"К3 (Примеры): {k3_score}/3\n"
    
    # Итоговый балл
    text += f"\n<b>Итого: {result.total_score}/{result.max_score} баллов</b>\n\n"
    
    # Основная обратная связь
    if result.feedback:
        text += f"{result.feedback}\n"
    
    # Детальный анализ если есть
    if hasattr(result, 'detailed_analysis') and result.detailed_analysis:
        if 'k1_comment' in result.detailed_analysis:
            text += f"\n<b>Обоснование:</b> {result.detailed_analysis['k1_comment']}\n"
        
        if 'k2_comment' in result.detailed_analysis:
            text += f"\n<b>Ответ:</b> {result.detailed_analysis['k2_comment']}\n"
        
        if 'k3_comment' in result.detailed_analysis:
            text += f"\n<b>Примеры:</b> {result.detailed_analysis['k3_comment']}\n"
    
    # Рекомендации
    if hasattr(result, 'suggestions') and result.suggestions:
        text += "\n💡 <b>Рекомендации:</b>\n"
        for suggestion in result.suggestions:
            text += f"• {suggestion}\n"
    
    # Фактические ошибки
    if hasattr(result, 'factual_errors') and result.factual_errors:
        text += "\n⚠️ <b>Обратите внимание:</b>\n"
        for error in result.factual_errors:
            if isinstance(error, dict):
                text += f"• {error.get('error', str(error))}"
                if 'correction' in error:
                    text += f" → {error['correction']}"
                text += "\n"
            else:
                text += f"• {error}\n"
    
    return text