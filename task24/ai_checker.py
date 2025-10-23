import logging
import json
from typing import Dict, Any, List, Optional, Tuple
from core.ai_service import get_ai_service

logger = logging.getLogger(__name__)


class PlanAIChecker:
    """AI-ассистент для проверки планов по обществознанию (Задание 24 ЕГЭ)"""
    
    def __init__(self):
        self.ai_service = get_ai_service()
        
        # ========== НОВОЕ: Якорные примеры из методички ==========
        self.ANCHOR_EXAMPLES = """
ПРИМЕРЫ ИЗ ОФИЦИАЛЬНОЙ МЕТОДИЧКИ КИМ ЕГЭ 2024:

❌ ПРИМЕР ОШИБКИ (К2 = 0):
План №2 по теме "Политические партии":
- Пункт "г) лишняя, некорректная" → ОШИБКА
- Итоговая оценка: К1=3, К2=0
- Причина: некорректная формулировка в подпункте

❌ ПРИМЕР МНОЖЕСТВЕННЫХ ОШИБОК (К2 = 0):
План №5:
- Множественные формулировки помечены как "ошибка/неточность"
- Итоговая оценка: К1=3, К2=0
- Причина: наличие фактических ошибок

❌ ПРИМЕР НЕДОСТАТОЧНОЙ ДЕТАЛИЗАЦИИ (К1 = 0):
План №9:
- "возможно три и более подпункта" (только 2 детализированных)
- Итоговая оценка: К1=0, К2=0
- Причина: не соответствует критерию "сложный план"

⚠️ АБСТРАКТНО-ФОРМАЛЬНЫЕ ПУНКТЫ (НЕ ЗАСЧИТЫВАЮТСЯ):
- "Понятие политической партии" БЕЗ раскрытия
- "Виды..." БЕЗ конкретных видов
- "Функции..." БЕЗ перечисления функций
ВАЖНО: Такие пункты не считаются раскрывающими тему!

✅ ПРАВИЛО ПРО 2 ПОДПУНКТА:
"Количество подпунктов должно быть не менее трёх, 
ЗА ИСКЛЮЧЕНИЕМ случаев, когда с точки зрения 
общественных наук возможны только два подпункта"
Примеры допустимых 2 подпунктов:
- Уровни научного познания: эмпирический, теоретический
- Типы партийных систем: однопартийная, двухпартийная (в узком смысле)
"""
    
    async def check_plan_relevance(
        self, 
        user_plan: str, 
        topic: str,
        etalon_points: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        УЛУЧШЕННАЯ проверка релевантности плана теме
        
        ИЗМЕНЕНИЯ:
        - Добавлены якорные примеры
        - Чёткие критерии для обязательных пунктов
        - Проверка на абстрактно-формальные пункты
        
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
        
        # ИЗМЕНЕНО: Более строгий system_prompt с примерами
        system_prompt = f"""Ты - строгий эксперт ЕГЭ по обществознанию, проверяющий задание 24.
Твоя задача - оценить соответствие плана ученика теме и требованиям ЕГЭ 2025.

{self.ANCHOR_EXAMPLES}

КРИТИЧЕСКИ ВАЖНО:
1. Для К1=3 требуется ВСЕ ТРИ обязательных пункта + детализация минимум 3 пунктов
2. Абстрактно-формальные пункты НЕ засчитываются
3. Будь СТРОГИМ, но справедливым"""

        prompt = f"""Проверь план ученика по теме: "{topic}"

План ученика:
{user_plan}

Эталонные ключевые аспекты темы (ОБЯЗАТЕЛЬНЫЕ пункты отмечены):
{etalon_text}

Требования ЕГЭ 2025 для "сложного плана":
- Минимум 3 пункта, раскрывающих тему по существу (не абстрактно-формальные!)
- Минимум 3 из них должны быть детализированы подпунктами
- В каждом детализированном пункте минимум 3 подпункта
  (исключение: 2 подпункта допустимы, если больше невозможно по содержанию)

ПРОВЕРЬ КАЖДЫЙ ПУНКТ:
1. Раскрывает ли он тему ПО СУЩЕСТВУ или это абстрактно-формальный заголовок?
   Пример ПЛОХОГО пункта: "Понятие государства" (без раскрытия)
   Пример ХОРОШЕГО пункта: "Признаки государства: а) территория; б) суверенитет..."

2. Есть ли ВСЕ ОБЯЗАТЕЛЬНЫЕ пункты из эталона?

3. Достаточно ли детализированы пункты?

Оцени:
1. Соответствует ли план заявленной теме (is_relevant: true/false)
2. Уверенность в оценке (confidence: 0.0-1.0)
3. Основные проблемы плана (issues: список строк)
4. Конкретные рекомендации по улучшению (suggestions: список строк)
5. Какие ключевые аспекты темы упущены (missing_key_aspects: список строк)
6. Степень покрытия темы (coverage_score: 0.0-1.0)

Обрати особое внимание на:
- Все ли ОБЯЗАТЕЛЬНЫЕ пункты из эталона раскрыты в плане ученика
- Нет ли абстрактно-формальных пунктов без содержания
- Корректность использования обществоведческих терминов
- Логическую структуру и последовательность изложения
- Соответствие подпунктов основным пунктам"""

        try:
            result = await self.ai_service.get_json_completion(
                prompt,
                system_prompt=system_prompt,
                temperature=0.2  # Низкая температура для строгости
            )

            if not result:
                logger.error("Не удалось получить ответ от AI")
                return self._default_relevance_result()

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
        КРИТИЧЕСКИ УЛУЧШЕННАЯ проверка фактических ошибок
        
        ИЗМЕНЕНИЯ:
        - ✅ Строгое определение, что считается "ошибкой" для К2=0
        - ✅ Добавлены примеры из методички
        - ✅ Температура снижена до 0.1 для максимальной точности
        - ✅ Чёткая классификация severity
        
        ВАЖНО: По критериям ЕГЭ ОДНА ошибка = К2=0!
        
        Returns:
            List[{
                "error": str,  # Точная цитата ошибки
                "correction": str,  # Правильный вариант
                "explanation": str,  # Объяснение
                "severity": str,  # high/medium/low
                "location": str  # Место в плане
            }]
        """
        
        # ИЗМЕНЕНО: Строгий system_prompt с чёткими критериями ошибок
        system_prompt = f"""Ты - строгий эксперт ЕГЭ по обществознанию. 
Твоя задача - найти ТОЛЬКО фактические ошибки и некорректные формулировки.

{self.ANCHOR_EXAMPLES}

КРИТЕРИИ ДЛЯ К2=0 (что считается ОШИБКОЙ):
1. Фактические ошибки:
   - Неправильные определения понятий
   - Искажение научных концепций
   - Неверные исторические факты
   
2. Некорректные формулировки:
   - Логические противоречия
   - Смешивание разных понятий
   - "Лишние, некорректные" пункты (из примера №2)

ЧТО НЕ СЧИТАЕТСЯ ОШИБКОЙ:
- Неполное раскрытие (это влияет на К1, не на К2)
- Отсутствие деталей
- Другая формулировка, но правильная по сути
- Стилистические недочёты

Будь МАКСИМАЛЬНО СТРОГИМ. Если сомневаешься - лучше отметь как ошибку."""

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

Найди ВСЕ фактические ошибки и некорректные формулировки, которые должны привести к К2=0.

Для каждой ошибки укажи:
- error: ТОЧНАЯ цитата неправильной формулировки из плана (не перефразируй!)
- correction: правильный вариант формулировки
- explanation: подробное объяснение, почему это ошибка с точки зрения обществознания
- severity: уровень критичности (high/medium/low)
- location: где в плане находится (например, "пункт 2, подпункт б")

Классификация severity:
- high: ГРУБЫЕ фактические ошибки, искажающие суть понятий
  Пример: "демократия - это власть одного человека"
  
- medium: Неточности в формулировках, смешивание понятий
  Пример: "политическая партия - это государственный орган"
  
- low: Непринципиальные неточности, не влияющие на К2
  Пример: "избирательная система обеспечивает выборы" (слишком общо, но не ошибка)

ВАЖНО: 
- Возвращай ТОЛЬКО реальные ошибки, не придумывай
- Если ошибок нет, верни пустой список []
- Для К2=0 достаточно ОДНОЙ ошибки severity=high или medium"""

        try:
            result = await self.ai_service.get_json_completion(
                prompt,
                system_prompt=system_prompt,
                temperature=0.1  # ИЗМЕНЕНО: Минимальная температура для точности (было без указания)
            )

            if not result or not isinstance(result, list):
                return []

            # Фильтруем и валидируем результаты
            validated_errors = []
            for error in result:
                if self._validate_error_entry(error):
                    validated_errors.append(error)
            
            # ИЗМЕНЕНО: Ограничиваем 3 ошибками (было 5)
            # Если нашли хотя бы одну high/medium - этого достаточно для К2=0
            return validated_errors[:3]
            
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
        УЛУЧШЕННАЯ проверка качества подпунктов
        
        ИЗМЕНЕНИЯ:
        - Учтено правило "2 подпункта иногда допустимы"
        - Проверка конкретности vs абстрактности
        
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
        
        # ИЗМЕНЕНО: Добавлено правило про 2 подпункта
        system_prompt = f"""Ты - эксперт ЕГЭ по обществознанию. 
Оцени качество подпунктов в контексте основного пункта плана.

{self.ANCHOR_EXAMPLES}

ПРАВИЛО ПРО КОЛИЧЕСТВО ПОДПУНКТОВ:
- Обычно требуется минимум 3 подпункта
- НО: 2 подпункта допустимы, если с точки зрения науки больше невозможно
  Примеры: уровни познания (эмпирический, теоретический), 
           основные типы систем (однопартийная, двухпартийная)

Будь строгим в оценке релевантности и качества."""

        etalon_info = ""
        if etalon_subpoints:
            etalon_info = f"""
Эталонные подпункты для сравнения:
{self._format_subpoints(etalon_subpoints)}
"""

        # ИЗМЕНЕНО: Добавлен параметр для проверки допустимости 2 подпунктов
        prompt = f"""Тема плана: "{topic_context}"
Пункт плана: "{point_text}"
Подпункты ученика (всего {len(subpoints)}):
{self._format_subpoints(subpoints)}
{etalon_info}

Для каждого подпункта оцени:
1. Релевантность основному пункту (is_relevant: true/false)
2. Качество раскрытия (quality: 0.0-1.0)
3. Наличие фактических ошибок (has_errors: true/false)
4. Конкретность и содержательность (is_specific: true/false)

ДОПОЛНИТЕЛЬНО:
5. Если подпунктов только 2 - оцени, допустимо ли это по содержанию?
   (two_subpoints_acceptable: true/false)
   Причина, если допустимо (two_subpoints_reason: строка)

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
        system_prompt = f"""Ты - эксперт ЕГЭ, сравнивающий план ученика с эталонным планом.
Оцени, насколько план ученика соответствует эталону по содержанию и структуре.

{self.ANCHOR_EXAMPLES}"""

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
- match_quality: качество соответствия (0.0-1.0)

ВАЖНО: Учитывай не только наличие пункта, но и его содержательность.
Абстрактно-формальный пункт не засчитывается!"""

        try:
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
        УЛУЧШЕННАЯ генерация персонализированной обратной связи
        
        ИЗМЕНЕНИЯ:
        - ✅ Temperature снижен с 0.7 до 0.4
        - ✅ Более строгий, но конструктивный тон
        - ✅ Ориентация на реальные критерии ЕГЭ
        """
        
        # ИЗМЕНЕНО: Более строгий system_prompt
        system_prompt = f"""Ты - опытный преподаватель обществознания, готовящий к ЕГЭ.
Дай развернутую, но СТРОГУЮ и объективную обратную связь по плану ученика.

{self.ANCHOR_EXAMPLES}

Используй педагогический подход:
1. СНАЧАЛА отметь конкретные достоинства (если есть)
2. ЗАТЕМ укажи на недостатки ПРЯМО и ЧЁТКО
3. ЗАВЕРШИ конкретными рекомендациями

Тон: дружелюбный, но честный и требовательный.
НЕ завышай оценку! НЕ смягчай проблемы!
Используй эмодзи умеренно.
Ответ должен быть на русском языке."""

        missed_text = "\n".join([f"- {point}" for point in missed_points]) if missed_points else "Нет"
        
        errors_text = ""
        if factual_errors:
            errors_text = "\n\nОбнаруженные ошибки (влияют на К2):\n"
            for error in factual_errors[:3]:
                errors_text += f"- {error.get('error', 'Ошибка')}\n"
                errors_text += f"  Правильно: {error.get('correction', '')}\n"

        comparison_text = ""
        if comparison_result:
            similarity = comparison_result.get('similarity_score', 0)
            comparison_text = f"\n\nСоответствие эталону: {int(similarity * 100)}%"

        prompt = f"""План ученика по теме "{topic}" получил оценку:
К1: {k1_score}/3 (раскрытие темы по существу)
К2: {k2_score}/1 (корректность формулировок)

Пропущенные ключевые аспекты темы:
{missed_text}
{errors_text}
{comparison_text}

План ученика:
{user_plan}

Напиши развёрнутую персональную обратную связь (5-7 предложений), включающую:

1. 💪 Сильные стороны плана (что удалось хорошо) - ТОЛЬКО если действительно есть
   
2. ❌ Главные проблемы (будь ПРЯМЫМ):
   - Если К1 < 3: чётко объясни, ПОЧЕМУ не хватило баллов
   - Если К2 = 0: укажи на конкретные ошибки
   - Если пропущены обязательные пункты: назови их
   
3. 💡 2-3 КОНКРЕТНЫХ совета по улучшению:
   - НЕ общие фразы ("добавьте деталей")
   - КОНКРЕТНЫЕ действия ("включите пункт про функции государства с подпунктами")
   
4. 📚 Что изучить дополнительно по этой теме (конкретные разделы)

5. 🎯 Честная оценка: готов ли ученик к экзамену по этой теме?

ВАЖНО: 
- НЕ повторяй баллы (они уже показаны)
- НЕ смягчай недостатки
- Фокусируйся на качественной, ЧЕСТНОЙ обратной связи"""

        try:
            result = await self.ai_service.get_completion(
                prompt,
                system_prompt=system_prompt,
                temperature=0.4  # ИЗМЕНЕНО: Снижено с 0.7 до 0.4 для меньшей вариативности
            )

            if result['success'] and result.get('text'):
                return result['text']
            
            # Fallback
            return self._generate_fallback_feedback(k1_score, k2_score)
            
        except Exception as e:
            logger.error(f"Ошибка генерации feedback: {e}")
            return self._generate_fallback_feedback(k1_score, k2_score)
    
    # ========== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==========
    
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
            "issues": result.get("issues", [])[:5],
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
            "etalon_coverage": max(0.0, min(1.0, result.get("etalon_coverage", 0.0))),
            # НОВОЕ: Проверка допустимости 2 подпунктов
            "two_subpoints_acceptable": result.get("two_subpoints_acceptable", False),
            "two_subpoints_reason": result.get("two_subpoints_reason", "")
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
            "etalon_coverage": 0.0,
            "two_subpoints_acceptable": False,
            "two_subpoints_reason": ""
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
        """
        УЛУЧШЕННЫЙ запасной вариант обратной связи
        
        ИЗМЕНЕНО: Более честные и строгие формулировки
        """
        if k1 == 3 and k2 == 1:
            return "Отличная работа! Ваш план полностью раскрывает тему и соответствует требованиям ЕГЭ. Продолжайте в том же духе! 🎉"
        elif k1 >= 2 and k2 == 1:
            return "Хороший план! Тема в целом раскрыта, но есть недочёты в детализации. Изучите эталонный план и добавьте недостающие аспекты. 💪"
        elif k1 >= 2 and k2 == 0:
            return "План структурно неплох, но содержит фактические ошибки. КРИТИЧЕСКИ ВАЖНО: исправьте ошибки, иначе К2=0! Проверьте корректность всех формулировок. ⚠️"
        elif k1 == 1 and k2 == 1:
            return "План требует серьёзной доработки. Тема раскрыта недостаточно. Добавьте больше ключевых аспектов и детализируйте пункты (минимум 3 подпункта в каждом). 📚"
        else:
            return "План не соответствует требованиям ЕГЭ. Внимательно изучите эталонный план, требования к структуре и критерии оценки. Не сдавайтесь, начните с основ! 🎯"


# ========== ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР ==========

_ai_checker_instance: Optional[PlanAIChecker] = None


def get_ai_checker() -> PlanAIChecker:
    """Получение глобального экземпляра AI-проверки"""
    global _ai_checker_instance
    
    if _ai_checker_instance is None:
        _ai_checker_instance = PlanAIChecker()
    
    return _ai_checker_instance