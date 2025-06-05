import logging
import json
from typing import Dict, Any, List, Optional, Tuple
from core.ai_service import get_ai_service

logger = logging.getLogger(__name__)


class PlanAIChecker:
    """AI-ассистент для проверки планов по обществознанию"""
    
    def __init__(self):
        self.ai_service = get_ai_service()
    
    async def check_plan_relevance(
        self, 
        user_plan: str, 
        topic: str,
        etalon_points: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Проверка релевантности плана теме с помощью AI
        
        Returns:
            {
                "is_relevant": bool,
                "confidence": float (0-1),
                "issues": List[str],
                "suggestions": List[str]
            }
        """
        # Форматируем эталонные пункты
        etalon_text = self._format_etalon_points(etalon_points)
        
        system_prompt = """Ты - эксперт ЕГЭ по обществознанию, специализирующийся на проверке планов (задание 24).
Твоя задача - оценить соответствие плана ученика теме и требованиям ЕГЭ."""

        prompt = f"""Проверь план ученика по теме: "{topic}"

План ученика:
{user_plan}

Эталонные ключевые аспекты темы:
{etalon_text}

Оцени:
1. Соответствует ли план заявленной теме (is_relevant: true/false)
2. Уверенность в оценке (confidence: 0.0-1.0)
3. Основные проблемы плана (issues: список строк)
4. Конкретные рекомендации по улучшению (suggestions: список строк)

Обрати внимание на:
- Раскрытие ключевых аспектов темы
- Логику изложения
- Корректность обществоведческих терминов
- Наличие фактических ошибок"""

        result = await self.ai_service.get_json_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.2
        )
        
        if not result:
            logger.error("Не удалось получить ответ от AI")
            return {
                "is_relevant": True,  # По умолчанию считаем релевантным
                "confidence": 0.5,
                "issues": [],
                "suggestions": []
            }
        
        return result
    
    async def check_subpoints_quality(
        self,
        point_text: str,
        subpoints: List[str],
        topic_context: str
    ) -> Dict[str, Any]:
        """
        Проверка качества подпунктов
        
        Returns:
            {
                "relevant_count": int,
                "total_quality_score": float (0-1),
                "subpoint_analysis": List[Dict],
                "improvement_suggestions": List[str]
            }
        """
        system_prompt = """Ты - эксперт ЕГЭ по обществознанию. 
Оцени качество подпунктов в контексте основного пункта плана."""

        prompt = f"""Тема плана: "{topic_context}"
Пункт плана: "{point_text}"
Подпункты:
{self._format_subpoints(subpoints)}

Для каждого подпункта оцени:
1. Релевантность основному пункту (is_relevant: true/false)
2. Качество раскрытия (quality: 0.0-1.0)
3. Наличие фактических ошибок (has_errors: true/false)

Также дай:
- Общее количество релевантных подпунктов (relevant_count)
- Общую оценку качества подпунктов (total_quality_score: 0.0-1.0)
- Анализ каждого подпункта (subpoint_analysis: список)
- Предложения по улучшению (improvement_suggestions: список строк)"""

        result = await self.ai_service.get_json_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.2
        )
        
        if not result:
            # Возвращаем нейтральную оценку
            return {
                "relevant_count": len(subpoints),
                "total_quality_score": 0.7,
                "subpoint_analysis": [],
                "improvement_suggestions": []
            }
        
        return result
    
    async def generate_personalized_feedback(
        self,
        user_plan: str,
        topic: str,
        k1_score: int,
        k2_score: int,
        missed_points: List[str]
    ) -> str:
        """
        Генерация персонализированной обратной связи
        """
        system_prompt = """Ты - доброжелательный преподаватель обществознания.
Дай конструктивную обратную связь по плану ученика. Будь позитивным, но честным.
Используй эмодзи для наглядности. Ответ должен быть на русском языке."""

        missed_text = "\n".join([f"- {point}" for point in missed_points]) if missed_points else "Нет"

        prompt = f"""План ученика по теме "{topic}" получил оценку:
К1: {k1_score}/3, К2: {k2_score}/1

Пропущенные ключевые аспекты:
{missed_text}

План ученика:
{user_plan}

Напиши персональную обратную связь (3-4 предложения), включающую:
1. Что хорошо в плане
2. Главную проблему (если есть)
3. Конкретный совет по улучшению
4. Мотивирующее завершение

Не повторяй оценки и баллы - они уже показаны ученику."""

        result = await self.ai_service.get_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.7  # Больше креативности для feedback
        )
        
        if result["success"]:
            return result["text"]
        else:
            return ""
    
    async def check_factual_errors(
        self,
        user_plan: str,
        topic: str
    ) -> List[Dict[str, str]]:
        """
        Проверка фактических ошибок в плане
        
        Returns:
            List[{"error": str, "correction": str, "explanation": str}]
        """
        system_prompt = """Ты - эксперт по обществознанию. 
Найди и исправь фактические ошибки в плане ученика. Будь строгим, но справедливым."""

        prompt = f"""Проверь план на фактические ошибки по теме: "{topic}"

План ученика:
{user_plan}

Найди ВСЕ фактические ошибки и для каждой укажи:
- error: неправильная формулировка
- correction: правильный вариант
- explanation: краткое объяснение ошибки

Если ошибок нет, верни пустой список.
Обращай внимание на:
- Неправильное использование терминов
- Искажение определений
- Фактические неточности
- Логические противоречия"""

        result = await self.ai_service.get_json_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.1  # Минимальная температура для точности
        )
        
        if not result or not isinstance(result, list):
            return []
        
        return result
    
    def _format_etalon_points(self, points: List[Dict[str, Any]]) -> str:
        """Форматирование эталонных пунктов для промпта"""
        formatted = []
        for i, point in enumerate(points, 1):
            if isinstance(point, dict):
                text = point.get('point_text', '')
                if point.get('is_potentially_key'):
                    formatted.append(f"{i}. {text} (ОБЯЗАТЕЛЬНЫЙ)")
                else:
                    formatted.append(f"{i}. {text}")
        return "\n".join(formatted)
    
    def _format_subpoints(self, subpoints: List[str]) -> str:
        """Форматирование подпунктов для промпта"""
        return "\n".join([f"{i+1}. {sp}" for i, sp in enumerate(subpoints)])


# Глобальный экземпляр
_ai_checker_instance: Optional[PlanAIChecker] = None


def get_ai_checker() -> PlanAIChecker:
    """Получение глобального экземпляра AI-проверки"""
    global _ai_checker_instance
    
    if _ai_checker_instance is None:
        _ai_checker_instance = PlanAIChecker()
    
    return _ai_checker_instance