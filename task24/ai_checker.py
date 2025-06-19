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
                "suggestions": List[str],
                "missing_key_aspects": List[str],
                "coverage_score": float (0-1)
            }
        """
        etalon_text = self._format_etalon_points(etalon_points)
        
        system_prompt = """Ты - эксперт ЕГЭ по обществознанию, специализирующийся на проверке планов (задание 24).
Твоя задача - оценить соответствие плана ученика теме и требованиям ЕГЭ 2025.
Будь строгим в оценке, но конструктивным в рекомендациях."""

        prompt = f"""Проверь план ученика по теме: "{topic}"

План ученика:
{user_plan}

Эталонные ключевые аспекты темы (ОБЯЗАТЕЛЬНЫЕ пункты отмечены):
{etalon_text}

Требования ЕГЭ 2025:
- Минимум 3 пункта, раскрывающих тему по существу
- Минимум 3 из них должны быть детализированы подпунктами
- В каждом детализированном пункте минимум 3 подпункта

Оцени:
1. Соответствует ли план заявленной теме (is_relevant: true/false)
2. Уверенность в оценке (confidence: 0.0-1.0)
3. Основные проблемы плана (issues: список строк)
4. Конкретные рекомендации по улучшению (suggestions: список строк)
5. Какие ключевые аспекты темы упущены (missing_key_aspects: список строк)
6. Степень покрытия темы (coverage_score: 0.0-1.0)

Обрати особое внимание на:
- Все ли ОБЯЗАТЕЛЬНЫЕ пункты из эталона раскрыты в плане ученика
- Корректность использования обществоведческих терминов
- Логическую структуру и последовательность изложения
- Соответствие подпунктов основным пунктам
- Наличие фактических ошибок или неточностей"""

        try:
            async with self.ai_service:
                result = await self.ai_service.get_json_completion(
                    prompt,
                    system_prompt=system_prompt,
                    temperature=0.2
                )

                if not result:
                    logger.error("Не удалось получить ответ от AI")
                    return self._default_relevance_result()

                # Валидация результата
                return self._validate_relevance_result(result)
                
        except Exception as e:
            logger.error(f"Ошибка при проверке релевантности: {e}")
            return self._default_relevance_result()
    
    async def check_factual_errors(
        self,
        user_plan: str,
        topic: str,
        etalon_data: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, str]]:
        """
        Углубленная проверка фактических ошибок в плане
        
        Returns:
            List[{
                "error": str, 
                "correction": str, 
                "explanation": str,
                "severity": str (low/medium/high),
                "location": str
            }]
        """
        system_prompt = """Ты - эксперт по обществознанию с глубокими знаниями теории. 
Твоя задача - найти и исправить ВСЕ фактические ошибки и неточности в плане ученика.
Будь особенно внимателен к:
- Неправильному использованию терминов
- Искажению определений и понятий
- Фактическим неточностям
- Логическим противоречиям
- Смешиванию понятий из разных областей знания"""

        etalon_info = ""
        if etalon_data:
            etalon_info = f"""
Эталонная информация по теме для сверки:
{json.dumps(etalon_data.get('key_concepts', {}), ensure_ascii=False, indent=2)}
"""

        prompt = f"""Проверь план на фактические ошибки по теме: "{topic}"

План ученика:
{user_plan}
{etalon_info}

Найди ВСЕ фактические ошибки, неточности и некорректные формулировки.
Для каждой ошибки укажи:
- error: точная цитата неправильной формулировки из плана
- correction: правильный вариант
- explanation: подробное объяснение, почему это ошибка
- severity: уровень критичности (low/medium/high)
- location: где в плане находится ошибка (номер пункта/подпункта)

Классификация severity:
- high: грубые фактические ошибки, искажающие суть понятий
- medium: неточности в формулировках, неполные определения
- low: стилистические недочеты, непринципиальные неточности

Если ошибок нет, верни пустой список []."""

        try:
            async with self.ai_service:
                result = await self.ai_service.get_json_completion(
                    prompt,
                    system_prompt=system_prompt,
                    temperature=0.1  # Минимальная температура для точности
                )

                if not result or not isinstance(result, list):
                    return []

                # Фильтруем и валидируем результаты
                validated_errors = []
                for error in result:
                    if self._validate_error_entry(error):
                        validated_errors.append(error)
                
                return validated_errors[:5]  # Ограничиваем количество ошибок
                
        except Exception as e:
            logger.error(f"Ошибка при проверке фактических ошибок: {e}")
            return []
    
    async def check_subpoints_quality(
        self,
        point_text: str,
        subpoints: List[str],
        topic_context: str,
        etalon_subpoints: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Детальная проверка качества подпунктов
        
        Returns:
            {
                "relevant_count": int,
                "total_quality_score": float (0-1),
                "subpoint_analysis": List[Dict],
                "improvement_suggestions": List[str],
                "matches_etalon": bool,
                "etalon_coverage": float (0-1)
            }
        """
        system_prompt = """Ты - эксперт ЕГЭ по обществознанию. 
Оцени качество подпунктов в контексте основного пункта плана.
Будь строгим в оценке релевантности и качества."""

        etalon_info = ""
        if etalon_subpoints:
            etalon_info = f"""
Эталонные подпункты для сравнения:
{self._format_subpoints(etalon_subpoints)}
"""

        prompt = f"""Тема плана: "{topic_context}"
Пункт плана: "{point_text}"
Подпункты ученика:
{self._format_subpoints(subpoints)}
{etalon_info}

Для каждого подпункта оцени:
1. Релевантность основному пункту (is_relevant: true/false)
2. Качество раскрытия (quality: 0.0-1.0)
3. Наличие фактических ошибок (has_errors: true/false)
4. Конкретность и содержательность (is_specific: true/false)

Также дай общую оценку:
- Количество действительно релевантных подпунктов (relevant_count)
- Общая оценка качества (total_quality_score: 0.0-1.0)
- Детальный анализ каждого подпункта (subpoint_analysis)
- Конкретные предложения по улучшению (improvement_suggestions)
- Соответствует ли набор подпунктов эталону (matches_etalon: true/false)
- Степень покрытия эталонных подпунктов (etalon_coverage: 0.0-1.0)

Критерии оценки quality:
- 0.8-1.0: отличный подпункт, конкретный и содержательный
- 0.5-0.7: приемлемый, но требует доработки
- 0.2-0.4: слабый, слишком общий или неточный
- 0.0-0.1: нерелевантный или содержит грубые ошибки"""

        try:
            async with self.ai_service:
                result = await self.ai_service.get_json_completion(
                    prompt,
                    system_prompt=system_prompt,
                    temperature=0.2
                )

                if not result:
                    return self._default_subpoints_result(len(subpoints))

                return self._validate_subpoints_result(result, len(subpoints))
                
        except Exception as e:
            logger.error(f"Ошибка при проверке подпунктов: {e}")
            return self._default_subpoints_result(len(subpoints))
    
    async def compare_with_etalon(
        self,
        user_plan: str,
        parsed_user_plan: List[Tuple[str, List[str]]],
        etalon_data: Dict[str, Any],
        topic: str
    ) -> Dict[str, Any]:
        """
        Сравнение плана пользователя с эталонным планом
        
        Returns:
            {
                "similarity_score": float (0-1),
                "matched_points": List[Dict],
                "missing_critical_points": List[str],
                "extra_good_points": List[str],
                "structural_match": float (0-1),
                "recommendations": List[str]
            }
        """
        system_prompt = """Ты - эксперт ЕГЭ, сравнивающий план ученика с эталонным планом.
Оцени, насколько план ученика соответствует эталону по содержанию и структуре."""

        etalon_points = etalon_data.get('points_data', [])
        etalon_formatted = self._format_full_etalon_plan(etalon_points)

        prompt = f"""Сравни план ученика с эталонным планом по теме: "{topic}"

План ученика:
{user_plan}

Эталонный план:
{etalon_formatted}

Проанализируй:
1. Общее сходство планов (similarity_score: 0.0-1.0)
2. Какие пункты эталона нашли отражение в плане ученика (matched_points)
3. Какие критически важные пункты упущены (missing_critical_points)
4. Какие дополнительные хорошие пункты есть у ученика (extra_good_points)
5. Насколько структура соответствует эталону (structural_match: 0.0-1.0)
6. Конкретные рекомендации по улучшению (recommendations)

Для matched_points укажи:
- etalon_point: текст пункта из эталона
- user_point: соответствующий пункт ученика
- match_quality: качество соответствия (0.0-1.0)"""

        try:
            async with self.ai_service:
                result = await self.ai_service.get_json_completion(
                    prompt,
                    system_prompt=system_prompt,
                    temperature=0.3
                )

                if not result:
                    return self._default_comparison_result()

                return self._validate_comparison_result(result)
                
        except Exception as e:
            logger.error(f"Ошибка при сравнении с эталоном: {e}")
            return self._default_comparison_result()
    
    async def generate_personalized_feedback(
        self,
        user_plan: str,
        topic: str,
        k1_score: int,
        k2_score: int,
        missed_points: List[str],
        factual_errors: Optional[List[Dict]] = None,
        comparison_result: Optional[Dict] = None
    ) -> str:
        """
        Генерация развернутой персонализированной обратной связи
        """
        system_prompt = """Ты - опытный и доброжелательный преподаватель обществознания.
Дай развернутую, конструктивную и мотивирующую обратную связь по плану ученика.
Используй педагогический подход: сначала отметь достоинства, затем укажи на недостатки,
заверши конкретными рекомендациями и словами поддержки.
Используй эмодзи для наглядности. Ответ должен быть на русском языке."""

        missed_text = "\n".join([f"- {point}" for point in missed_points]) if missed_points else "Нет"
        
        errors_text = ""
        if factual_errors:
            errors_text = "\n\nОбнаруженные неточности:\n"
            for error in factual_errors[:3]:  # Максимум 3 ошибки
                errors_text += f"- {error.get('error', 'Ошибка')}\n"

        comparison_text = ""
        if comparison_result:
            similarity = comparison_result.get('similarity_score', 0)
            comparison_text = f"\n\nСоответствие эталону: {int(similarity * 100)}%"

        prompt = f"""План ученика по теме "{topic}" получил оценку:
К1: {k1_score}/3, К2: {k2_score}/1

Пропущенные ключевые аспекты:
{missed_text}
{errors_text}
{comparison_text}

План ученика:
{user_plan}

Напиши развернутую персональную обратную связь (5-7 предложений), включающую:
1. 💪 Сильные стороны плана (что удалось хорошо)
2. 📍 Главные проблемы (если есть) - сформулируй деликатно
3. 💡 2-3 конкретных совета по улучшению
4. 🎯 Что изучить дополнительно по этой теме
5. 🌟 Мотивирующее завершение с оценкой потенциала

Тон: дружелюбный, поддерживающий, но честный.
НЕ повторяй баллы - они уже показаны. Фокусируйся на качественной обратной связи."""

        try:
            async with self.ai_service:
                result = await self.ai_service.get_completion(
                    prompt,
                    system_prompt=system_prompt,
                    temperature=0.7
                )

                if result["success"]:
                    return result["text"]
                else:
                    return self._generate_fallback_feedback(k1_score, k2_score)
                    
        except Exception as e:
            logger.error(f"Ошибка генерации feedback: {e}")
            return self._generate_fallback_feedback(k1_score, k2_score)
    
    # Вспомогательные методы
    
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
    
    def _format_full_etalon_plan(self, points: List[Dict[str, Any]]) -> str:
        """Форматирование полного эталонного плана с подпунктами"""
        formatted = []
        for i, point in enumerate(points, 1):
            if isinstance(point, dict):
                text = point.get('point_text', '')
                marker = " (ОБЯЗАТЕЛЬНЫЙ)" if point.get('is_potentially_key') else ""
                formatted.append(f"{i}. {text}{marker}")
                
                subpoints = point.get('sub_points', [])
                if subpoints:
                    for j, subpoint in enumerate(subpoints):
                        formatted.append(f"   {chr(ord('а') + j)}) {subpoint}")
        
        return "\n".join(formatted)
    
    def _format_subpoints(self, subpoints: List[str]) -> str:
        """Форматирование подпунктов для промпта"""
        return "\n".join([f"{chr(ord('а') + i)}) {sp}" for i, sp in enumerate(subpoints)])
    
    def _validate_relevance_result(self, result: Dict) -> Dict[str, Any]:
        """Валидация результата проверки релевантности"""
        validated = {
            "is_relevant": result.get("is_relevant", True),
            "confidence": max(0.0, min(1.0, result.get("confidence", 0.5))),
            "issues": result.get("issues", [])[:5],  # Максимум 5 проблем
            "suggestions": result.get("suggestions", [])[:5],
            "missing_key_aspects": result.get("missing_key_aspects", [])[:5],
            "coverage_score": max(0.0, min(1.0, result.get("coverage_score", 0.5)))
        }
        return validated
    
    def _validate_error_entry(self, error: Dict) -> bool:
        """Валидация записи об ошибке"""
        required_fields = ["error", "correction", "explanation"]
        return all(field in error and error[field] for field in required_fields)
    
    def _validate_subpoints_result(self, result: Dict, subpoints_count: int) -> Dict[str, Any]:
        """Валидация результата проверки подпунктов"""
        validated = {
            "relevant_count": min(result.get("relevant_count", subpoints_count), subpoints_count),
            "total_quality_score": max(0.0, min(1.0, result.get("total_quality_score", 0.5))),
            "subpoint_analysis": result.get("subpoint_analysis", [])[:subpoints_count],
            "improvement_suggestions": result.get("improvement_suggestions", [])[:3],
            "matches_etalon": result.get("matches_etalon", False),
            "etalon_coverage": max(0.0, min(1.0, result.get("etalon_coverage", 0.0)))
        }
        return validated
    
    def _validate_comparison_result(self, result: Dict) -> Dict[str, Any]:
        """Валидация результата сравнения с эталоном"""
        validated = {
            "similarity_score": max(0.0, min(1.0, result.get("similarity_score", 0.0))),
            "matched_points": result.get("matched_points", [])[:10],
            "missing_critical_points": result.get("missing_critical_points", [])[:5],
            "extra_good_points": result.get("extra_good_points", [])[:3],
            "structural_match": max(0.0, min(1.0, result.get("structural_match", 0.0))),
            "recommendations": result.get("recommendations", [])[:5]
        }
        return validated
    
    def _default_relevance_result(self) -> Dict[str, Any]:
        """Результат по умолчанию для проверки релевантности"""
        return {
            "is_relevant": True,
            "confidence": 0.5,
            "issues": [],
            "suggestions": [],
            "missing_key_aspects": [],
            "coverage_score": 0.7
        }
    
    def _default_subpoints_result(self, count: int) -> Dict[str, Any]:
        """Результат по умолчанию для проверки подпунктов"""
        return {
            "relevant_count": count,
            "total_quality_score": 0.7,
            "subpoint_analysis": [],
            "improvement_suggestions": [],
            "matches_etalon": False,
            "etalon_coverage": 0.0
        }
    
    def _default_comparison_result(self) -> Dict[str, Any]:
        """Результат по умолчанию для сравнения с эталоном"""
        return {
            "similarity_score": 0.5,
            "matched_points": [],
            "missing_critical_points": [],
            "extra_good_points": [],
            "structural_match": 0.5,
            "recommendations": []
        }
    
    def _generate_fallback_feedback(self, k1: int, k2: int) -> str:
        """Запасной вариант обратной связи"""
        if k1 == 3 and k2 == 1:
            return "Отличная работа! Ваш план полностью раскрывает тему. Продолжайте в том же духе! 🎉"
        elif k1 >= 2:
            return "Хороший план! Есть небольшие недочёты, но в целом тема раскрыта. Обратите внимание на детализацию подпунктов. 👍"
        else:
            return "План требует доработки. Изучите эталонный план и попробуйте включить больше ключевых аспектов темы. Не сдавайтесь! 💪"


# Глобальный экземпляр
_ai_checker_instance: Optional[PlanAIChecker] = None


def get_ai_checker() -> PlanAIChecker:
    """Получение глобального экземпляра AI-проверки"""
    global _ai_checker_instance
    
    if _ai_checker_instance is None:
        _ai_checker_instance = PlanAIChecker()
    
    return _ai_checker_instance