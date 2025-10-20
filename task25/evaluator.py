"""AI-проверка для задания 25 через YandexGPT.

Обновленная версия с оптимизированными промптами для критериев К1, К2, К3.
Включает детальную проверку российского контекста и связи между критериями.
"""

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

        # ИСПРАВЛЕНО: используем self.criteria_scores вместо self.scores
        scores = self.criteria_scores if hasattr(self, 'criteria_scores') and self.criteria_scores else {}

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

        # ИСПРАВЛЕНО: используем self.detailed_feedback вместо self.detailed_analysis
        if self.detailed_feedback:
            text += "\n<b>Детальный анализ:</b>\n"

            # Комментарии по критериям
            if 'k1_comment' in self.detailed_feedback:
                text += f"\n<b>Обоснование:</b> {self.detailed_feedback['k1_comment']}\n"

            if 'k2_comment' in self.detailed_feedback:
                text += f"\n<b>Ответ:</b> {self.detailed_feedback['k2_comment']}\n"

            if 'k3_comment' in self.detailed_feedback:
                text += f"\n<b>Примеры:</b> {self.detailed_feedback['k3_comment']}\n"

                # Найденные примеры
                if 'k3_examples_found' in self.detailed_feedback:
                    examples = self.detailed_feedback['k3_examples_found']
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
    LENIENT = "lenient"      # Мягкая проверка
    STANDARD = "standard"    # Стандартная проверка
    STRICT = "strict"        # Строгая проверка
    EXPERT = "expert"        # Экспертная проверка


class Task25AIEvaluator:
    """AI-оценщик для задания 25."""
    
    def __init__(self, strictness: StrictnessLevel = StrictnessLevel.STANDARD):
        """
        Инициализация оценщика.
        
        Args:
            strictness: Уровень строгости проверки
        """
        self.strictness = strictness
        self.ai_service = None
        
        if not AI_EVALUATOR_AVAILABLE:
            logger.warning("AI evaluator not available")
            return
        
        try:
            # Получаем API ключи из переменных окружения
            api_key = os.getenv("YANDEX_GPT_API_KEY")
            folder_id = os.getenv("YANDEX_GPT_FOLDER_ID")
            
            if not api_key or not folder_id:
                logger.error("YANDEX_GPT_API_KEY и YANDEX_GPT_FOLDER_ID должны быть установлены")
                self.ai_service = None
                return
            
            # Настраиваем YandexGPT
            config = YandexGPTConfig(
                api_key=api_key,
                folder_id=folder_id,
                model=YandexGPTModel.PRO,
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
            # ОБНОВЛЁННЫЙ СТАНДАРТНЫЙ ПРОМПТ с детальными критериями
            base_prompt = """Ты - эксперт ЕГЭ по обществознанию, проверяющий задание 25.

═══════════════════════════════════════════════════════════════
КРИТЕРИИ ОЦЕНИВАНИЯ ПО ФИПИ:
═══════════════════════════════════════════════════════════════

К1 - ОБОСНОВАНИЕ (0-2 балла):

2 БАЛЛА - когда ОДНОВРЕМЕННО выполнены ВСЕ условия:
✓ Обоснование с опорой на обществоведческие знания
✓ Дано в НЕСКОЛЬКИХ РАСПРОСТРАНЁННЫХ ПРЕДЛОЖЕНИЯХ (минимум 2-3 предложения, каждое не менее 5-7 слов)
✓ НЕ содержит ошибок, неточностей и искажений
✓ РАСКРЫВАЕТ причинно-следственные И/ИЛИ функциональные связи
✓ Используются обществоведческие термины

1 БАЛЛ - когда:
• Обоснование в нескольких распространённых предложениях, НО содержит отдельные неточности 
  ИЛИ не полностью раскрывает причинно-следственные связи

0 БАЛЛОВ - когда:
• Обоснование в ОДНОМ ПРЕДЛОЖЕНИИ или СЛОВОСОЧЕТАНИИ
• БЕЗ опоры на обществоведческие знания (на бытовом уровне)
• Обоснование отсутствует
• Содержит существенные ошибки

ПРИЗНАКИ КАЧЕСТВЕННОГО ОБОСНОВАНИЯ:
- Минимум 2-3 распространённых предложения
- Чёткая логика: тезис → аргумент → вывод
- Термины: "институт", "функция", "процесс", "механизм", "система"
- Явные связи: "что приводит к...", "в результате...", "обеспечивает...", "способствует..."

─────────────────────────────────────────────────────────────

К2 - ОТВЕТ НА ВОПРОС (0-1 балл):

1 БАЛЛ - когда ОДНОВРЕМЕННО:
✓ Дан правильный ответ
✓ Указано НЕОБХОДИМОЕ КОЛИЧЕСТВО элементов (обычно 3)
✓ Каждый элемент в ЯВНОМ ВИДЕ как САМОСТОЯТЕЛЬНЫЙ элемент
✓ Нет неверных позиций
✓ ОБЯЗАТЕЛЬНО: Если требуется "в РФ/России" - ВСЕ элементы реальны для РФ

0 БАЛЛОВ - когда:
• Указано МЕНЬШЕ требуемого количества
• Есть НЕВЕРНЫЕ позиции
• Ответ не дан в явном виде
• Не оформлен как самостоятельный элемент
• При требовании РФ - нереалистичные/иностранные элементы
• Ответ отсутствует

ПРОВЕРКА РОССИЙСКОГО КОНТЕКСТА:
Если в задании: "в РФ", "в России", "российского":
❌ НЕ ЗАСЧИТЫВАЕТСЯ: иностранные реалии, выдуманные элементы
✅ ЗАСЧИТЫВАЕТСЯ: только реальные российские институты/партии/меры

─────────────────────────────────────────────────────────────

К3 - ПРИМЕРЫ (0-3 балла):

БАЗОВЫЕ ПРАВИЛА:
✓ Максимум 3 балла (по 1 баллу за каждый пример)
✓ Каждый пример РАЗВЁРНУТО (минимум полное предложение)
✓ ОТДЕЛЬНЫЕ СЛОВА И СЛОВОСОЧЕТАНИЯ НЕ ЗАСЧИТЫВАЮТСЯ!
✓ Примеры иллюстрируют РАЗНЫЕ аспекты/функции
✓ Если требуется РФ - примеры ТОЛЬКО из российских реалий

3 БАЛЛА: три корректных развёрнутых примера, иллюстрирующих ТРИ РАЗНЫХ аспекта, без ошибок

2 БАЛЛА: два корректных примера ИЛИ 2-3 однотипных (засчитываются как один) 
         ИЛИ три примера корректны, но есть ошибки в ДОПОЛНИТЕЛЬНЫХ примерах

1 БАЛЛ: один корректный пример

0 БАЛЛОВ: примеры отсутствуют, не засчитаны, в виде слов/словосочетаний, абстрактные

КРИТИЧЕСКИ ВАЖНО:
❌ Если 2-3 примера иллюстрируют ОДНУ функцию → засчитываются как ОДИН пример
❌ Если есть дополнительные примеры с ошибками → максимум 1 балл
❌ Если пример - словосочетание ("выборы в Госдуму") → НЕ засчитывается
❌ Если требуется РФ, а указано "государство Z" → НЕ засчитывается

МИНИМУМ для засчитывания примера:
"[КТО] [ЧТО СДЕЛАЛ] [В КАКОЙ СИТУАЦИИ] [РЕЗУЛЬТАТ]"

═══════════════════════════════════════════════════════════════
СВЯЗЬ МЕЖДУ К2 И К3:
═══════════════════════════════════════════════════════════════

КРИТИЧЕСКИ ВАЖНО!
Если во втором пункте (К2) приведён ОШИБОЧНЫЙ элемент, то пример в К3, 
иллюстрирующий этот ошибочный элемент, АВТОМАТИЧЕСКИ НЕ ЗАСЧИТЫВАЕТСЯ!

Пример:
К2: 1. Элемент А ✓
    2. Элемент Б ✗ (ОШИБОЧНЫЙ!)
    3. Элемент В ✓

К3: Пример 1 для А - засчитывается ✓
    Пример 2 для Б - НЕ засчитывается ✗ (т.к. Б ошибочен!)
    Пример 3 для В - засчитывается ✓
    
→ К3: максимум 2 балла (не 3!)

═══════════════════════════════════════════════════════════════
ВАЖНЫЕ ИНСТРУКЦИИ:
═══════════════════════════════════════════════════════════════

1. Всегда проверяй РОССИЙСКИЙ КОНТЕКСТ когда упомянута РФ/Россия
2. Считай количество предложений в обосновании
3. Проверяй каждый пример на развёрнутость
4. Проверяй, иллюстрируют ли примеры РАЗНЫЕ функции/аспекты
5. Проверяй связь К2 и К3 - ошибочный элемент в К2 = незасчитанный пример в К3!
6. Проверяй дополнительные примеры на ошибки
7. Будь строгим но справедливым
"""
        
        # Дополнения в зависимости от строгости
        if self.strictness == StrictnessLevel.LENIENT:
            base_prompt += "\n\nУРОВЕНЬ ПРОВЕРКИ: МЯГКИЙ - Засчитывай частично правильные ответы."
        elif self.strictness == StrictnessLevel.STRICT:
            base_prompt += "\n\nУРОВЕНЬ ПРОВЕРКИ: СТРОГИЙ - Применяй СТРОГИЕ критерии ФИПИ. Требуй полного соответствия."
        elif self.strictness == StrictnessLevel.EXPERT:
            base_prompt += "\n\nУРОВЕНЬ ПРОВЕРКИ: ЭКСПЕРТНЫЙ - МАКСИМАЛЬНАЯ строгость. Любые неточности снижают балл."
        
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
        """Строит ОБНОВЛЁННЫЙ промпт для оценки ответа."""
        task_text = topic.get('task_text', '')
        
        # Разбираем части задания если они есть
        parts = topic.get('parts', {})
        part1 = parts.get('part1', '')
        part2 = parts.get('part2', '')
        part3 = parts.get('part3', '')
        
        # Определяем требования российского контекста
        requires_russia = any(keyword in task_text.lower() or 
                            keyword in part2.lower() or 
                            keyword in part3.lower() 
                            for keyword in ['рф', 'россии', 'российск', 'в россии', 'в рф'])
        
        prompt = f"""Оцени ответ ученика на задание 25.

ЗАДАНИЕ:
{task_text}

Части задания:
1) {part1}
2) {part2}
3) {part3}

ОТВЕТ УЧЕНИКА:
{answer}

═══════════════════════════════════════════════════════════════
ПОШАГОВЫЙ АЛГОРИТМ ПРОВЕРКИ:
═══════════════════════════════════════════════════════════════

ШАГ 1: ПРОВЕРКА К1 (Обоснование)

1.1. Подсчитай количество предложений в обосновании
     → Если 1 предложение или словосочетание → 0 баллов
     
1.2. Проверь распространённость предложений (5+ слов каждое)
     → Если нет → снижай оценку
     
1.3. Проверь наличие ОБЩЕСТВОВЕДЧЕСКИХ ТЕРМИНОВ
     → Если только бытовой язык → 0 баллов
     
1.4. Проверь раскрытие ПРИЧИННО-СЛЕДСТВЕННЫХ/ФУНКЦИОНАЛЬНЫХ связей
     → Ищи связки: "поэтому", "следовательно", "способствует", "приводит к"
     → Если связи не раскрыты → максимум 1 балл
     
1.5. Проверь на ФАКТИЧЕСКИЕ ОШИБКИ
     → Серьёзные ошибки → 0 баллов
     → Мелкие неточности → 1 балл

─────────────────────────────────────────────────────────────

ШАГ 2: ПРОВЕРКА К2 (Ответ на вопрос)

2.1. Определи требуемое количество элементов из текста задания
     → Обычно требуется 3 элемента
     
2.2. Проверь формат ответа
     → Ответ должен быть оформлен ОТДЕЛЬНЫМ пунктом
     → Должна быть явная нумерация: "1. ... 2. ... 3. ..."
     → Если элементы в одном предложении через запятую → НЕ засчитывается
     
2.3. Подсчитай количество указанных элементов
     → Если меньше требуемого → 0 баллов
     
2.4. Проверь каждый элемент на КОРРЕКТНОСТЬ
     → Фактически верен?
     → Соответствует типу требуемого объекта?
     
2.5. {"ПРОВЕРЬ РОССИЙСКИЙ КОНТЕКСТ (ОБЯЗАТЕЛЬНО!):" if requires_russia else ""}
     {"→ ВСЕ элементы должны быть реальными для современной России" if requires_russia else ""}
     {"→ Примеры НЕПРАВИЛЬНЫХ элементов: иностранные партии, законы других стран" if requires_russia else ""}
     {"→ Примеры ПРАВИЛЬНЫХ элементов: Единая Россия, КПРФ, ЛДПР, Новые люди, Справедливая Россия" if requires_russia else ""}
     
2.6. Проверь на НЕВЕРНЫЕ позиции
     → Если хотя бы ОДНА неверная → 0 баллов

2.7. ЗАПОМНИ: какие элементы из К2 ОШИБОЧНЫЕ (для проверки К3!)

─────────────────────────────────────────────────────────────

ШАГ 3: ПРОВЕРКА К3 (Примеры)

3.1. Подсчитай количество примеров

3.2. Проверь РАЗВЁРНУТОСТЬ каждого примера
     → Полное предложение с деталями? ✓
     → Словосочетание ("выборы в Госдуму")? ✗
     → Минимум: "[КТО] [ЧТО СДЕЛАЛ] [ГДЕ/КОГДА] [РЕЗУЛЬТАТ]"
     
3.3. {"ПРОВЕРЬ РОССИЙСКИЙ КОНТЕКСТ (ОБЯЗАТЕЛЬНО!):" if requires_russia else ""}
     {"→ Каждый пример должен содержать российские реалии" if requires_russia else ""}
     {"→ 'Государство Z' вместо России → НЕ засчитывается" if requires_russia else ""}
     {"→ Иностранные примеры → НЕ засчитывается" if requires_russia else ""}
     
3.4. Проверь, иллюстрируют ли примеры РАЗНЫЕ функции/аспекты
     → Если 2-3 примера об ОДНОЙ функции → засчитываются как ОДИН пример
     → Пример: все три про "электоральную функцию" → 1 балл, не 3!
     
3.5. КРИТИЧЕСКИ ВАЖНО: Проверь связь с К2!
     → Если элемент в К2 ОШИБОЧНЫЙ, то пример к нему НЕ ЗАСЧИТЫВАЕТСЯ
     → Пример: если в К2 указана несуществующая партия, то пример про неё → 0 баллов
     
3.6. Проверь ДОПОЛНИТЕЛЬНЫЕ примеры (если >3)
     → Если есть ошибки в дополнительных → максимум 1 балл за К3!
     
3.7. Проверь фактическую корректность примеров

═══════════════════════════════════════════════════════════════

Верни результат в формате JSON:
{{
    "k1_score": 0-2,
    "k1_comment": "детальный комментарий с указанием, что учтено/не учтено",
    "k2_score": 0-1,
    "k2_comment": "комментарий по ответу, какие элементы верны/неверны",
    "k2_elements": [{{"element": "название", "is_correct": true/false, "comment": "почему"}}],
    "k3_score": 0-3,
    "k3_comment": "комментарий по примерам",
    "k3_examples": [
        {{
            "number": 1,
            "text": "краткое описание примера",
            "is_valid": true/false,
            "is_expanded": true/false,
            "matches_russian_context": true/false,
            "function": "название функции/аспекта",
            "related_k2_element": "элемент из К2",
            "related_k2_element_correct": true/false,
            "comment": "почему засчитан или не засчитан"
        }}
    ],
    "total_score": 0-6,
    "general_feedback": "общий комментарий",
    "suggestions": ["конкретный совет 1", "конкретный совет 2"],
    "factual_errors": ["ошибка 1", "ошибка 2"]
}}

ВАЖНО: 
- Будь максимально детален в комментариях
- Для каждого незасчитанного элемента/примера объясни ПОЧЕМУ
- Давай КОНКРЕТНЫЕ рекомендации по улучшению
- Проверяй связь К2 и К3!
- {"Обязательно проверяй российский контекст!" if requires_russia else ""}"""
        
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
        
        # ВАЖНО: Всегда пересчитываем общий балл как сумму критериев
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
        
        # ВАЖНО: Используем сумму баллов по критериям, а не total_score от AI
        total_score = scores['k1_score'] + scores['k2_score'] + scores['k3_score']
        
        # Формируем основную обратную связь на основе реальных баллов
        if total_score >= 5:
            feedback = "🎉 Отличная работа! Ответ соответствует всем критериям."
        elif total_score >= 3:
            feedback = "👍 Хорошо! Есть небольшие недочёты."
        else:
            feedback = "📝 Нужно доработать ответ. Изучите рекомендации."
        
        # Добавляем общий комментарий если есть (но не переопределяем feedback полностью)
        if result.get('general_feedback') and total_score >= 3:
            feedback += f"\n\n{result['general_feedback']}"
        
        # Создаём детальный анализ
        detailed_feedback = {
            'k1_comment': result.get('k1_comment', ''),
            'k2_comment': result.get('k2_comment', ''),
            'k3_comment': result.get('k3_comment', ''),
            'k3_examples_found': result.get('k3_examples_found', [])
        }
        
        # Создаем расширенный результат
        eval_result = Task25EvaluationResult(
            criteria_scores=scores,
            total_score=total_score,  # Используем пересчитанный балл
            max_score=6,
            feedback=feedback,
            detailed_feedback=detailed_feedback,
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
            detailed_feedback=None,
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
                result['total_score'] = min(6, int(total_match.group(1)))
            else:
                result['total_score'] = result['k1_score'] + result['k2_score'] + result['k3_score']
            
            # Пытаемся извлечь общий комментарий
            result['general_feedback'] = response[:500] if len(response) > 500 else response
            
        except Exception as e:
            logger.error(f"Error parsing text response: {e}")
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
    
    # Используем result.criteria_scores
    if hasattr(result, 'criteria_scores') and result.criteria_scores:
        text += "<b>Баллы по критериям:</b>\n"
        
        # Проверяем разные форматы ключей
        k1_score = result.criteria_scores.get('k1_score', result.criteria_scores.get('К1', 0))
        k2_score = result.criteria_scores.get('k2_score', result.criteria_scores.get('К2', 0))
        k3_score = result.criteria_scores.get('k3_score', result.criteria_scores.get('К3', 0))
        
        text += f"К1 (Обоснование): {k1_score}/2\n"
        text += f"К2 (Ответ): {k2_score}/1\n"
        text += f"К3 (Примеры): {k3_score}/3\n"
    
    # Итоговый балл
    text += f"\n<b>Итого: {result.total_score}/{result.max_score} баллов</b>\n\n"
    
    # Основная обратная связь
    if result.feedback:
        text += f"{result.feedback}\n"
    
    # Используем detailed_feedback
    if hasattr(result, 'detailed_feedback') and result.detailed_feedback:
        if 'k1_comment' in result.detailed_feedback:
            text += f"\n<b>Обоснование:</b> {result.detailed_feedback['k1_comment']}\n"
        
        if 'k2_comment' in result.detailed_feedback:
            text += f"\n<b>Ответ:</b> {result.detailed_feedback['k2_comment']}\n"
        
        if 'k3_comment' in result.detailed_feedback:
            text += f"\n<b>Примеры:</b> {result.detailed_feedback['k3_comment']}\n"
    
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