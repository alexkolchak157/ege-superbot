"""AI-проверка для задания 19 через YandexGPT."""

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
    
    


class StrictnessLevel(Enum):
    """Уровни строгости проверки."""
    LENIENT = "Мягкий"
    STANDARD = "Стандартный" 
    STRICT = "Строгий"
    EXPERT = "Экспертный"


class Task19AIEvaluator(BaseAIEvaluator if AI_EVALUATOR_AVAILABLE else object):
    """AI-проверщик для задания 19 с настраиваемой строгостью."""
    
    def __init__(self, strictness: StrictnessLevel = StrictnessLevel.STANDARD):
        self.strictness = strictness
        
        if AI_EVALUATOR_AVAILABLE:
            requirements = TaskRequirements(
                task_number=19,
                task_name="Примеры социальных объектов",
                max_score=3,
                criteria=[
                    {
                        "name": "К1",
                        "max_score": 3,
                        "description": "Корректность примеров (по 1 баллу за каждый)"
                    }
                ],
                description="Приведите три примера, иллюстрирующие обществоведческое положение"
            )
            super().__init__(requirements)
        else:
            self.requirements = TaskRequirements(
                task_number=19,
                task_name="Примеры социальных объектов",
                max_score=3,
                criteria=[{"name": "К1", "max_score": 3, "description": "Корректность примеров"}],
                description="Приведите три примера, иллюстрирующие обществоведческое положение"
            )
        
        # Инициализируем сервис если доступен
        self.ai_service = None
        if AI_EVALUATOR_AVAILABLE:
            try:
                config = YandexGPTConfig.from_env()
                # Выбираем модель в зависимости от строгости
                if strictness in [StrictnessLevel.STRICT, StrictnessLevel.EXPERT]:
                    config.model = YandexGPTModel.PRO
                else:
                    config.model = YandexGPTModel.LITE
                
                # Настройка температуры
                if strictness == StrictnessLevel.LENIENT:
                    config.temperature = 0.4
                elif strictness == StrictnessLevel.STANDARD:
                    config.temperature = 0.3
                else:
                    config.temperature = 0.2
                    
                self.config = config
                logger.info(f"Task19 AI evaluator configured with {strictness.value} strictness")
            except Exception as e:
                logger.error(f"Failed to configure AI service: {e}")
                self.config = None
    
    def get_system_prompt(self) -> str:
        """Системный промпт для YandexGPT."""
        base_prompt = """Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 19.

ВАЖНЫЕ ПРАВИЛА ДЛЯ ЗАДАНИЯ 19:
1. В отличие от задания 19, здесь НЕ нужны конкретные примеры
2. Требуются суждения АБСТРАКТНОГО характера с элементами обобщения
3. Суждения должны быть более широкого объёма и менее конкретного содержания
4. Каждое суждение должно быть сформулировано как распространённое предложение
5. Суждения должны содержать элементы обобщения

КРИТЕРИИ ОЦЕНИВАНИЯ:
- 3 балла: приведены все требуемые суждения правильного типа
- 2 балла: приведено на одно суждение меньше требуемого
- 1 балл: приведено на два суждения меньше требуемого  
- 0 баллов: приведен только один аргумент ИЛИ рассуждения общего характера

ШТРАФЫ:
- Если наряду с требуемыми суждениями есть 2+ дополнительных с ошибками → 0 баллов
- Если есть 1 дополнительное с ошибкой → минус 1 балл от фактического

ЧТО СЧИТАЕТСЯ ПРАВИЛЬНЫМ СУЖДЕНИЕМ ДЛЯ ЗАДАНИЯ 19:
- Содержит элементы обобщения (способствует, приводит к, влияет на, обеспечивает, позволяет, создает, формирует, развивает, препятствует, ограничивает, снижает, повышает, улучшает, ухудшает, определяет, зависит от)
- НЕ содержит конкретных примеров (дат, имён, названий конкретных стран/организаций/компаний)
- Является распространённым предложением (не менее 5 слов)
- Соответствует требованию задания
- Содержит причинно-следственные связи

ЧТО НЕ ЗАСЧИТЫВАЕТСЯ:
- Конкретные примеры (например: "В 2020 году в России...", "Компания Apple...", "Во Франции...")
- Упоминание конкретных личностей, дат, событий
- Слишком конкретное содержание без обобщения
- Отдельные слова и словосочетания
- Общие рассуждения без чёткой аргументации
- Суждения, не соответствующие типу (например, негативный вместо позитивного)

ВАЖНО: Будь строг в оценке, но справедлив. Учитывай российский контекст.

При проверке:
- Будь лаконичен в комментариях
- Давай конкретные, практические советы
- Не используй общие фразы типа "нужно больше стараться"
- Для каждого неудачного суждения предложи, как его переформулировать"""

        # Модификация в зависимости от уровня строгости
        if self.strictness == StrictnessLevel.LENIENT:
            base_prompt += "\n\nУРОВЕНЬ: МЯГКИЙ - засчитывай суждения с небольшими недочётами."
        elif self.strictness == StrictnessLevel.STANDARD:
            base_prompt += "\n\nУРОВЕНЬ: СТАНДАРТНЫЙ - следуй критериям, но прощай мелкие недочёты."
        elif self.strictness == StrictnessLevel.STRICT:
            base_prompt += "\n\nУРОВЕНЬ: СТРОГИЙ - требуй полного соответствия критериям ФИПИ."
        elif self.strictness == StrictnessLevel.EXPERT:
            base_prompt += "\n\nУРОВЕНЬ: ЭКСПЕРТНЫЙ - максимальная строгость, как на реальном экзамене."
        
        return base_prompt
    
    def evaluate_answer(self, question: str, answer: str, sample_answer: str) -> Dict[str, Any]:
        """Оценивает ответ на задание 19 через YandexGPT."""
        try:
            # Инициализация переменных в самом начале
            total_score = 0
            max_score = 3
            
            prompt = f"""Оцени ответ ученика на задание 19 ЕГЭ по обществознанию.
            
    Задание: {question}

    Ответ ученика:
    {answer}

    Критерии оценивания (максимум 3 балла):
    - Правильно приведены три примера (1 балл за каждый пример)
    - Примеры должны быть конкретными, а не абстрактными
    - Примеры должны четко иллюстрировать теоретическое положение из задания

    Уровень строгости проверки: {self.strictness.value}

    {self._get_strictness_instructions()}

    Проанализируй каждый пример и верни результат в формате JSON:
    {{
        "example1": {{
            "score": 0 или 1,
            "comment": "краткий комментарий"
        }},
        "example2": {{
            "score": 0 или 1,
            "comment": "краткий комментарий"
        }},
        "example3": {{
            "score": 0 или 1,
            "comment": "краткий комментарий"
        }},
        "total_score": сумма баллов (0-3),
        "feedback": "общий комментарий к ответу",
        "suggestions": ["рекомендация 1", "рекомендация 2"],
        "factual_errors": ["ошибка 1", "ошибка 2"] (если есть)
    }}"""

            # Вызов AI
            response = self.ai_service.generate_response(prompt)
            
            # Парсинг ответа
            result = self._parse_ai_response(response)
            
            # Подсчет баллов (с защитой от ошибок)
            if 'example1' in result and isinstance(result['example1'], dict):
                total_score += result['example1'].get('score', 0)
            if 'example2' in result and isinstance(result['example2'], dict):
                total_score += result['example2'].get('score', 0)
            if 'example3' in result and isinstance(result['example3'], dict):
                total_score += result['example3'].get('score', 0)
            
            # Создание детального анализа
            detailed_analysis = {}
            for i in range(1, 4):
                key = f'example{i}'
                if key in result and isinstance(result[key], dict):
                    detailed_analysis[f'Пример {i}'] = result[key]
            
            # Формирование результата
            return {
                'scores': {
                    'К1': total_score  # Используем инициализированную переменную
                },
                'total_score': total_score,
                'max_score': max_score,
                'feedback': result.get('feedback', 'Проверка завершена'),
                'detailed_analysis': detailed_analysis,
                'suggestions': result.get('suggestions', []),
                'factual_errors': result.get('factual_errors', [])
            }
            
        except Exception as e:
            logger.error(f"Evaluation error: {e}")
            # Возвращаем базовый результат при ошибке
            return {
                'scores': {'К1': 0},
                'total_score': 0,
                'max_score': 3,
                'feedback': 'Не удалось выполнить автоматическую проверку',
                'detailed_analysis': {},
                'suggestions': ['Попробуйте отправить ответ позже'],
                'factual_errors': []
            }
    
    def _basic_evaluation(self, answer: str, topic: str) -> EvaluationResult:
        """Базовая оценка без AI."""
        arguments = [arg.strip() for arg in answer.split('\n') if arg.strip()]
        score = min(len(arguments), 3) if len(arguments) <= 3 else 2
        
        # Проверяем на наличие конкретных примеров
        concrete_indicators = [
            'например', 'в 20', 'году', 'компания', 'страна',
            'россия', 'сша', 'китай', 'франция', 'германия'
        ]
        
        has_concrete = any(indicator in answer.lower() for indicator in concrete_indicators)
        if has_concrete and score > 0:
            score = max(0, score - 1)
        
        return EvaluationResult(
            scores={"К1": score},
            total_score=score,
            max_score=3,
            feedback=f"Обнаружено суждений: {len(arguments)}",
            detailed_analysis={
                "arguments_count": len(arguments),
                "score": score,
                "has_concrete_examples": has_concrete
            },
            suggestions=[
                "Используйте больше обобщающих конструкций",
                "Избегайте конкретных примеров",
                "Формулируйте развёрнутые предложения"
            ],
            factual_errors=[]
        )
    
    def _parse_response(self, response: Dict[str, Any], answer: str, topic: str) -> EvaluationResult:
            """Парсинг ответа от YandexGPT."""
            try:
                score = response.get("score", 0)
                
                # Формируем краткую обратную связь
                feedback = response.get("feedback", "")
                
                # Добавляем информацию о засчитанных суждениях (кратко)
                if response.get("valid_arguments"):
                    feedback += f"\n\n✅ <b>Засчитанные суждения:</b>\n"
                    for i, arg in enumerate(response["valid_arguments"], 1):
                        feedback += f"{i}. {arg.get('comment', 'Суждение корректно')}\n"
                
                # Добавляем информацию о незасчитанных суждениях с конкретными советами
                if response.get("invalid_arguments"):
                    feedback += f"\n\n❌ <b>Не засчитанные суждения:</b>\n"
                    for arg in response["invalid_arguments"]:
                        feedback += f"{arg['number']}. {arg.get('reason', 'Не соответствует критериям')}\n"
                        if arg.get('improvement'):
                            feedback += f"   💡 <i>Совет: {arg['improvement']}</i>\n"
                
                # Добавляем информацию о штрафах (если есть)
                if response.get("penalty_applied"):
                    feedback += f"\n⚠️ <b>Применён штраф:</b> {response.get('penalty_reason', '')}"
                
                return EvaluationResult(
                    scores={"К1": score},
                    total_score=score,
                    max_score=3,
                    feedback=feedback,
                    detailed_analysis=response,
                    suggestions=response.get("suggestions", []),
                    factual_errors=response.get("factual_errors", [])
                )
                
            except Exception as e:
                logger.error(f"Error parsing YandexGPT response: {e}")
                return self._basic_evaluation(answer, topic)