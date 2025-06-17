"""AI-проверка для задания 25 через YandexGPT."""

import logging
import os
import json
from enum import Enum
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Безопасный импорт
try:
    from core.ai_evaluator import (
        BaseAIEvaluator,
        EvaluationResult,
        TaskRequirements,
    )
    from core.ai_service import YandexGPTService, YandexGPTConfig, YandexGPTModel
    AI_EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI evaluator components not available: {e}")
    AI_EVALUATOR_AVAILABLE = False
    
    # Заглушки для работы без AI
    @dataclass
    class TaskRequirements:
        task_number: int
        task_name: str
        max_score: int
        criteria: List[Dict]
        description: str
    
    @dataclass
    class EvaluationResult:
        scores: Dict[str, int]
        total_score: int
        max_score: int
        feedback: str
        detailed_analysis: Optional[Dict] = None
        suggestions: Optional[List[str]] = None
        factual_errors: Optional[List[str]] = None
    
    class BaseAIEvaluator:
        def __init__(self, requirements: TaskRequirements):
            self.requirements = requirements
    
    class YandexGPTService:
        pass
    
    class YandexGPTConfig:
        pass
    
    class YandexGPTModel:
        LITE = "yandexgpt-lite"
        PRO = "yandexgpt"


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
            config = YandexGPTConfig(
                api_key=os.getenv('YANDEX_GPT_API_KEY'),
                folder_id=os.getenv('YANDEX_GPT_FOLDER_ID'),
                model=YandexGPTModel.PRO,  # Используем PRO для сложного задания
                temperature=self._get_temperature(),
                max_tokens=3000
            )
            self.ai_service = YandexGPTService(config)
            logger.info(f"Task25 AI service initialized with {self.strictness.value} strictness")
        except Exception as e:
            logger.error(f"Failed to initialize AI service: {e}")
            self.ai_service = None
    
    def _get_temperature(self) -> float:
        """Возвращает температуру в зависимости от уровня строгости."""
        temps = {
            StrictnessLevel.LENIENT: 0.3,
            StrictnessLevel.STANDARD: 0.2,
            StrictnessLevel.STRICT: 0.1,
            StrictnessLevel.EXPERT: 0.05
        }
        return temps.get(self.strictness, 0.2)
    
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
            
            # Получаем оценку от AI
            response = await self.ai_service.complete(
                system_prompt=self.get_system_prompt(),
                user_prompt=eval_prompt
            )
            
            # Парсим результат
            result = self._parse_ai_response(response)
            
            # Валидируем и корректируем оценки
            validated_result = self._validate_scores(result)
            
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
    
    def _create_evaluation_result(self, result: Dict, topic: Dict) -> EvaluationResult:
        """Создаёт итоговый результат оценки."""
        # Формируем основную обратную связь
        feedback_parts = []
        
        # К1 - Обоснование
        k1_score = result.get('k1_score', 0)
        k1_comment = result.get('k1_comment', '')
        feedback_parts.append(f"<b>К1 (Обоснование):</b> {k1_score}/2")
        if k1_comment:
            feedback_parts.append(f"💡 {k1_comment}")
        
        # К2 - Ответ на вопрос
        k2_score = result.get('k2_score', 0)
        k2_comment = result.get('k2_comment', '')
        feedback_parts.append(f"\n<b>К2 (Ответ на вопрос):</b> {k2_score}/1")
        if k2_comment:
            feedback_parts.append(f"📝 {k2_comment}")
        
        # К3 - Примеры
        k3_score = result.get('k3_score', 0)
        k3_comment = result.get('k3_comment', '')
        feedback_parts.append(f"\n<b>К3 (Примеры):</b> {k3_score}/3")
        if k3_comment:
            feedback_parts.append(f"📚 {k3_comment}")
        
        # Найденные примеры
        examples_found = result.get('k3_examples_found', [])
        if examples_found:
            feedback_parts.append("\n<b>Засчитанные примеры:</b>")
            for i, example in enumerate(examples_found[:3], 1):
                feedback_parts.append(f"{i}. {example}")
        
        # Общий балл
        total_score = result.get('total_score', 0)
        feedback_parts.append(f"\n<b>Итого:</b> {total_score}/6 баллов")
        
        # Общий комментарий
        general_feedback = result.get('general_feedback', '')
        if general_feedback:
            feedback_parts.append(f"\n💭 {general_feedback}")
        
        # Фактические ошибки
        factual_errors = result.get('factual_errors', [])
        if factual_errors:
            feedback_parts.append("\n<b>❌ Фактические ошибки:</b>")
            for error in factual_errors:
                feedback_parts.append(f"• {error}")
        
        # Рекомендации
        suggestions = result.get('suggestions', [])
        if suggestions:
            feedback_parts.append("\n<b>💡 Рекомендации:</b>")
            for suggestion in suggestions:
                feedback_parts.append(f"• {suggestion}")
        
        # Добавляем информацию об уровне проверки
        feedback_parts.append(f"\n<i>Уровень проверки: {self.strictness.value}</i>")
        
        return EvaluationResult(
            scores={
                'k1': k1_score,
                'k2': k2_score,
                'k3': k3_score
            },
            total_score=total_score,
            max_score=6,
            feedback='\n'.join(feedback_parts),
            detailed_analysis=result,
            suggestions=suggestions,
            factual_errors=factual_errors
        )
    
    def _get_fallback_result(self) -> EvaluationResult:
        """Возвращает результат при недоступности AI."""
        return EvaluationResult(
            scores={'k1': 0, 'k2': 0, 'k3': 0},
            total_score=0,
            max_score=6,
            feedback=(
                "❌ <b>AI-проверка временно недоступна</b>\n\n"
                "К сожалению, автоматическая проверка сейчас невозможна.\n"
                "Пожалуйста, попробуйте позже или обратитесь к преподавателю.\n\n"
                "Для самостоятельной проверки убедитесь, что ваш ответ содержит:\n"
                "1. Развёрнутое обоснование (К1)\n"
                "2. Чёткий ответ на вопрос (К2)\n"
                "3. Три конкретных примера (К3)"
            ),
            detailed_analysis={},
            suggestions=[
                "Проверьте структуру ответа",
                "Убедитесь в наличии всех трёх частей",
                "Примеры должны быть конкретными и развёрнутыми"
            ],
            factual_errors=[]
        )

    def _parse_text_response(self, response: str) -> Dict:
        """Парсит текстовый ответ AI когда JSON не найден."""
        import re
        
        result = {
            'k1_score': 0,
            'k1_comment': '',
            'k2_score': 0,
            'k2_comment': '',
            'k3_score': 0,
            'k3_comment': '',
            'k3_examples_found': [],
            'total_score': 0,
            'general_feedback': '',
            'suggestions': [],
            'factual_errors': []
        }
        
        try:
            # Ищем оценки по критериям
            # К1
            k1_match = re.search(r'К1.*?(\d+).*?бал', response, re.IGNORECASE | re.DOTALL)
            if k1_match:
                result['k1_score'] = int(k1_match.group(1))
            
            # К2
            k2_match = re.search(r'К2.*?(\d+).*?бал', response, re.IGNORECASE | re.DOTALL)
            if k2_match:
                result['k2_score'] = int(k2_match.group(1))
            
            # К3
            k3_match = re.search(r'К3.*?(\d+).*?бал', response, re.IGNORECASE | re.DOTALL)
            if k3_match:
                result['k3_score'] = int(k3_match.group(1))
            
            # Общий балл
            total_match = re.search(r'(?:итого|всего|общий балл).*?(\d+)', response, re.IGNORECASE)
            if total_match:
                result['total_score'] = int(total_match.group(1))
            else:
                result['total_score'] = result['k1_score'] + result['k2_score'] + result['k3_score']
            
            # Ищем примеры
            examples_section = re.search(r'(?:примеры|засчитанные примеры):(.*?)(?:рекомендации|советы|ошибки|$)', 
                                       response, re.IGNORECASE | re.DOTALL)
            if examples_section:
                examples_text = examples_section.group(1)
                # Ищем нумерованные примеры
                example_matches = re.findall(r'\d+[.)]\s*(.+?)(?=\d+[.)]|$)', examples_text, re.DOTALL)
                result['k3_examples_found'] = [ex.strip() for ex in example_matches[:3]]
            
            # Ищем рекомендации
            suggestions_section = re.search(r'(?:рекомендации|советы):(.*?)(?:ошибки|$)', 
                                          response, re.IGNORECASE | re.DOTALL)
            if suggestions_section:
                suggestions_text = suggestions_section.group(1)
                suggestion_matches = re.findall(r'[•\-]\s*(.+?)(?=[•\-]|$)', suggestions_text, re.DOTALL)
                result['suggestions'] = [s.strip() for s in suggestion_matches]
            
            # Ищем ошибки
            errors_section = re.search(r'(?:ошибки|неточности):(.*?)$', response, re.IGNORECASE | re.DOTALL)
            if errors_section:
                errors_text = errors_section.group(1)
                error_matches = re.findall(r'[•\-]\s*(.+?)(?=[•\-]|$)', errors_text, re.DOTALL)
                result['factual_errors'] = [e.strip() for e in error_matches]
            
            # Если комментарии не найдены отдельно, берём часть текста
            if not result['k1_comment']:
                k1_section = re.search(r'К1[^:]*:(.*?)(?=К2|$)', response, re.IGNORECASE | re.DOTALL)
                if k1_section:
                    result['k1_comment'] = k1_section.group(1).strip()[:100]
            
            logger.info(f"Parsed text response: {result}")
            
        except Exception as e:
            logger.error(f"Error parsing text response: {e}")
        
        return result