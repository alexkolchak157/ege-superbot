"""AI-проверка для задания 19 через YandexGPT - ФИНАЛЬНАЯ ВЕРСИЯ V2.1."""

import logging
import os
import json
import re
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
    from core.ai_evaluator import BaseAIEvaluator
    from core.ai_service import YandexGPTService, YandexGPTConfig, YandexGPTModel
    AI_EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI evaluator components not available: {e}")
    AI_EVALUATOR_AVAILABLE = False

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
    """AI-проверщик для задания 19 с улучшенной проверкой конкретности."""
    
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
                if strictness in [StrictnessLevel.STRICT, StrictnessLevel.EXPERT]:
                    config.model = YandexGPTModel.PRO
                else:
                    config.model = YandexGPTModel.LITE
                
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
    
    def _check_russia_requirement(self, task_text: str) -> bool:
        """Проверяет, требуются ли в задании примеры про Россию."""
        russia_keywords = [
            r'\bРосси[ияю]',
            r'\bРФ\b',
            r'\bРоссийск[ойиеую]{1,3}',
            r'\bв\s+нашей\s+стране',
        ]
        for pattern in russia_keywords:
            if re.search(pattern, task_text, re.IGNORECASE):
                return True
        return False
    
    def _check_structure_requirement(self, task_text: str) -> Optional[str]:
        """Определяет, требуется ли особая структура ответа."""
        # Паттерны для разных типов структурных требований
        structure_patterns = [
            (r'сначала\s+\w+\s*,\s*затем\s+пример', 'сначала_затем'),
            (r'в\s+каждом\s+случае\s+\w+\s+пример', 'элемент_пример'),
            (r'приведите\s+пример[^.]+иллюстриру', 'элемент_пример'),
        ]
        
        for pattern, struct_type in structure_patterns:
            if re.search(pattern, task_text, re.IGNORECASE):
                return struct_type
        
        return None
    
    def get_system_prompt(self) -> str:
        """Улучшенный системный промпт с четкими критериями конкретности."""
        base_prompt = """Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 19.

КРИТИЧЕСКОЕ ПРАВИЛО: Пример должен быть КОНКРЕТНЫМ, а не общим рассуждением!

═══════════════════════════════════════════════════════════
ОБЯЗАТЕЛЬНЫЕ ПРИЗНАКИ КОНКРЕТНОГО ПРИМЕРА:
═══════════════════════════════════════════════════════════

1. КОНКРЕТНОЕ ЛИЦО ИЛИ ОРГАНИЗАЦИЯ:
   ✅ ПРАВИЛЬНО:
   - "Гражданин А добровольно заключил брак"
   - "Гражданка Т., разочарованная в политическом курсе, активно участвует"
   - "Супруги Петровы работают на комбинате"
   - "Корпорация BMW производит автомобили"
   - "Компания «Газпром» занимается добычей газа"
   - "Одиннадцатиклассница Софья поступила в вуз"
   - "Государство Z сократило расходы на 7%" (если нет требования про Россию)
   - "В стране Z была снижена ставка налога" (если нет требования про Россию)
   
   ❌ НЕПРАВИЛЬНО (слишком общо):
   - "Многие люди работают" 
   - "Студенты учатся в университетах"
   - "Компании производят товары"
   - "Граждане платят налоги"
   - "Человек идет в магазин"
   - "В России создают рабочие места" (без конкретной организации)
   - "Государство строит больницы" (без конкретики где/когда/какие)

2. КОНКРЕТНОЕ ДЕЙСТВИЕ ИЛИ СИТУАЦИЯ:
   ✅ ПРАВИЛЬНО:
   - "Константин Козлов получает арендную плату за переданную Обществу спасения на водах моторную лодку"
   - "Михаил стеснялся отвечать на уроке, но позже стал активнее работать"
   - "Телеканал «Звезда» осветил визит Президента РФ в Казахстан"
   - "Государство Z выпустило в обращение облигации государственного займа сроком на 5 лет"
   - "Правительство государства Z установило брачный возраст и условия регистрации брака"
   
   ❌ НЕПРАВИЛЬНО (общие рассуждения):
   - "В России создают большое количество рабочих мест" 
   - "Государство строит новые школы и больницы"
   - "У каждого человека есть телефон и компьютер"
   - "Многие люди пользуются интернетом"
   - "С наступлением НТП образование стало доступнее"

3. ДЕТАЛИ И КОНТЕКСТ:
   ✅ ПРАВИЛЬНО:
   - "Создатели фильма «Чебурашка» заработали более 6 миллиардов рублей"
   - "Выпускник Кирилл подал заявление в пять вузов на сайте «Госуслуги»"
   - "Агрофирма, выращивающая яблоки, открыла цех по производству детского питания"
   - "Государство Z сократило расходы на содержание государственного аппарата на 7%"
   - "Правительство государства Z выпустило облигации сроком на 5 лет"
   
   ❌ НЕПРАВИЛЬНО (без деталей):
   - "Фильмы зарабатывают деньги"
   - "Выпускники поступают в вузы"
   - "Компании открывают новые производства"
   - "Государство сокращает расходы"

═══════════════════════════════════════════════════════════
СПЕЦИАЛЬНЫЕ ПРАВИЛА:
═══════════════════════════════════════════════════════════

ПРАВИЛО 1: ВЫМЫШЛЕННЫЕ СТРАНЫ (важно!)
✅ ДОПУСКАЮТСЯ "страна Z", "государство Z" ТОЛЬКО если:
   - В задании НЕТ слов "Россия", "РФ", "российский"
   - Пример конкретный с деталями (не общее рассуждение)
   
   ПРИМЕРЫ правильного использования "страны Z":
   ✅ "Государство Z сократило расходы на государственный аппарат на 7%"
   ✅ "В стране Z была снижена ставка налога на добавленную стоимость"
   ✅ "Правительство государства Z выпустило облигации сроком на 5 лет"
   
   ПРИМЕРЫ неправильного:
   ❌ "В стране Z создают рабочие места" (слишком общо)
   ❌ "Государство Z строит больницы" (нет конкретики)

❌ ЗАПРЕЩЕНЫ вымышленные страны, если в задании есть:
   - "Россия", "РФ", "российский", "в нашей стране"
   - В этом случае требуются ТОЛЬКО примеры про Россию!

ПРАВИЛО 2: СТРУКТУРА ОТВЕТА (критично!)
Если в задании есть требование структуры типа:
- "сначала укажите функцию, затем пример"
- "сначала укажите меру, затем пример"
- "сначала укажите ряд процессов, затем соответствующие примеры"

То ОБЯЗАТЕЛЬНО проверь:
✅ Ученик СНАЧАЛА указал элемент (функцию/меру/процесс)
✅ Ученик ПОТОМ привел пример

ПРИМЕР правильной структуры:
✅ "1) Воспроизводство политической системы: на уроках обществознания 
    школьники страны Z изучают основы конституционного строя"

ПРИМЕР неправильной структуры:
❌ "На уроках обществознания школьники изучают конституционный строй"
   (не указана функция - "воспроизводство политической системы")

═══════════════════════════════════════════════════════════
ТИПИЧНЫЕ ОШИБКИ (НЕ ЗАСЧИТЫВАТЬ):
═══════════════════════════════════════════════════════════

❌ ОПИСАНИЕ ТЕНДЕНЦИЙ вместо примеров:
   - "В России создают рабочие места в военной сфере"
   - "Государство строит больницы по всей стране"
   - "С появлением Chat GPT люди лишились работы"

❌ АБСТРАКТНЫЕ УТВЕРЖДЕНИЯ:
   - "Все люди стремятся к образованию"
   - "Обычно компании нанимают работников"
   - "Как правило, государство поддерживает бизнес"

❌ ГИПОТЕТИЧЕСКИЕ ПРИМЕРЫ:
   - "Если человек хочет стать врачом, он..."
   - "Когда студент сдает экзамены, он..."

❌ СЛИШКОМ КРАТКИЕ ПРИМЕРЫ без деталей:
   - "Иван - студент"
   - "Петр работает"
   - "Мария учится"

❌ ОБЩИЕ РАССУЖДЕНИЯ с фразами:
   - "многие...", "все...", "обычно...", "как правило..."
   - "в России...", "в нашей стране..." (без конкретной организации)
   - "у каждого...", "практически у всех..."

❌ НАРУШЕНИЕ СТРУКТУРЫ:
   - Не указан элемент (функция/мера/процесс) перед примером
   - Указан только пример без элемента

❌ НАРУШЕНИЕ ТРЕБОВАНИЯ ПРО РОССИЮ:
   - В задании упомянута Россия, но пример про вымышленную страну
   - В задании упомянута Россия, но пример без российских реалий

═══════════════════════════════════════════════════════════
АЛГОРИТМ ПРОВЕРКИ:
═══════════════════════════════════════════════════════════

ШАГ 0: ПРОВЕРКА ТРЕБОВАНИЙ ЗАДАНИЯ
   - Есть ли требование про Россию?
   - Есть ли требование структуры (элемент → пример)?

ШАГ 1: Есть ли КОНКРЕТНОЕ ЛИЦО/ОРГАНИЗАЦИЯ с именем/названием?
   - ИЛИ конкретное лицо (Антон, гражданин А, супруги Петровы)
   - ИЛИ конкретная организация (BMW, Газпром, телеканал «Звезда»)
   - ИЛИ вымышленная страна (государство Z, страна Z) - только если нет требования про Россию
   - НЕТ → пример НЕ конкретный → 0 баллов

ШАГ 2: Описывает ли пример КОНКРЕТНУЮ СИТУАЦИЮ, а не общую тенденцию?
   - НЕТ → пример НЕ конкретный → 0 баллов

ШАГ 3: Есть ли ДЕТАЛИ (место, время, обстоятельства, цифры)?
   - НЕТ или мало → пример слабый или НЕ конкретный

ШАГ 4: Соблюдена ли СТРУКТУРА ответа (если требуется)?
   - НЕТ → пример не засчитан → 0 баллов

ШАГ 5: Соответствует ли пример требованию про РОССИЮ (если есть)?
   - НЕТ → пример не засчитан → 0 баллов

ШАГ 6: Это описание конкретного случая или общее рассуждение?
   - Общее рассуждение → 0 баллов

═══════════════════════════════════════════════════════════
КРИТЕРИИ ОЦЕНИВАНИЯ:
═══════════════════════════════════════════════════════════

3 балла: три конкретных примера с именами/названиями и деталями
2 балла: два конкретных примера
1 балл: один конкретный пример
0 баллов: нет ни одного конкретного примера ИЛИ все примеры абстрактны

ШТРАФЫ:
- Если >3 примеров и есть 2+ серьёзных ошибки → 0 баллов за всё
- Если 1 дополнительный пример с ошибкой → минус 1 балл
- Если нарушена структура ответа (элемент → пример) → 0 баллов за этот пример
- Если в задании требуется Россия, а пример не про Россию → 0 баллов

═══════════════════════════════════════════════════════════

ВАЖНО: Будь максимально строг в оценке КОНКРЕТНОСТИ. Общие рассуждения о тенденциях, статистике, "многих людях" - это НЕ примеры!"""

        # Модификация по уровню строгости
        if self.strictness == StrictnessLevel.LENIENT:
            base_prompt += "\n\nУРОВЕНЬ: МЯГКИЙ - засчитывай примеры с небольшими недочётами в деталях, но ТРЕБУЙ конкретности."
        elif self.strictness == StrictnessLevel.STANDARD:
            base_prompt += "\n\nУРОВЕНЬ: СТАНДАРТНЫЙ - следуй критериям, СТРОГО проверяй конкретность."
        elif self.strictness == StrictnessLevel.STRICT:
            base_prompt += "\n\nУРОВЕНЬ: СТРОГИЙ - требуй ПОЛНОГО соответствия критериям ФИПИ, особенно конкретности."
        elif self.strictness == StrictnessLevel.EXPERT:
            base_prompt += "\n\nУРОВЕНЬ: ЭКСПЕРТНЫЙ - максимальная строгость. НЕ засчитывай даже слегка абстрактные примеры."

        return base_prompt

    async def evaluate(self, answer: str, topic: str, **kwargs) -> EvaluationResult:
        """Оценка ответа через YandexGPT с улучшенной проверкой."""
        task_text = kwargs.get('task_text', '')

        if not AI_EVALUATOR_AVAILABLE or not self.config:
            return self._basic_evaluation(answer, topic)

        # Проверяем требования задания
        requires_russia = self._check_russia_requirement(task_text)
        structure_type = self._check_structure_requirement(task_text)

        # Формируем дополнительные инструкции
        extra_instructions = ""
        
        if requires_russia:
            extra_instructions += "\n⚠️ ВАЖНО: В задании упомянута РОССИЯ → примеры ДОЛЖНЫ быть про Россию!"
            extra_instructions += "\nВымышленные страны (государство Z) НЕ допускаются!"
            extra_instructions += "\nПримеры должны отражать российские реалии, законы, события."
        
        if structure_type:
            extra_instructions += "\n⚠️ ВАЖНО: В задании требуется СТРУКТУРА ответа!"
            extra_instructions += "\nКаждый пример должен содержать:"
            extra_instructions += "\n1) ЭЛЕМЕНТ (функция/мера/процесс/ряд)"
            extra_instructions += "\n2) ПРИМЕР, иллюстрирующий этот элемент"
            extra_instructions += "\nЕсли структура нарушена → пример НЕ засчитывается!"

        evaluation_prompt = f"""Проверь ответ на задание 19 ЕГЭ.

ЗАДАНИЕ: {task_text}

ТЕМА: {topic}

ОТВЕТ УЧЕНИКА:
{answer}
{extra_instructions}

═══════════════════════════════════════════════════════════
ПОШАГОВЫЙ АЛГОРИТМ ПРОВЕРКИ:
═══════════════════════════════════════════════════════════

ШАГ 0: АНАЛИЗ ТРЕБОВАНИЙ ЗАДАНИЯ
   - Требуются ли примеры про Россию? {"ДА - примеры ТОЛЬКО про Россию!" if requires_russia else "НЕТ - можно использовать вымышленные страны"}
   - Требуется ли структура (элемент → пример)? {"ДА - проверяй структуру!" if structure_type else "НЕТ"}

ШАГ 1: Подсчитай ОБЩЕЕ количество примеров в ответе

ШАГ 2: Если примеров >3, проверь КАЖДЫЙ на серьёзные ошибки
   - При 2+ серьёзных ошибках → 0 баллов за ВСЁ задание

ШАГ 3: Для КАЖДОГО примера последовательно проверь:

   3.1. СООТВЕТСТВИЕ ТРЕБОВАНИЮ ПРО РОССИЮ:
        {"✅ Описывает российские реалии/события/законы?" if requires_russia else "✅ Может быть про любую страну, включая вымышленную"}
        {"❌ Если НЕ про Россию → 0 баллов за этот пример" if requires_russia else ""}
        
   3.2. СОБЛЮДЕНИЕ СТРУКТУРЫ (если требуется):
        {"✅ Сначала указан элемент (функция/мера/процесс)?" if structure_type else ""}
        {"✅ Затем приведен пример?" if structure_type else ""}
        {"❌ Если структура нарушена → 0 баллов за этот пример" if structure_type else ""}

   3.3. КОНКРЕТНОСТЬ ЛИЦА/ОРГАНИЗАЦИИ:
        ✅ Есть имя/название? (Антон, BMW, "Газпром", супруги Петровы, государство Z)
        ❌ Общие слова? (человек, люди, многие, компании, государство без уточнения)
        
   3.4. КОНКРЕТНОСТЬ СИТУАЦИИ:
        ✅ Описана конкретная ситуация? (что именно сделал/произошло)
        ❌ Общее рассуждение? ("в России создают...", "у каждого есть...")
        
   3.5. НАЛИЧИЕ ДЕТАЛЕЙ:
        ✅ Есть детали? (место, время, обстоятельства, цифры)
        ❌ Слишком кратко? (2-3 слова без контекста)
        
   3.6. ТИП ВЫСКАЗЫВАНИЯ:
        ✅ Это конкретный пример?
        ❌ Это описание тенденции/статистики/общего явления?

   3.7. СООТВЕТСТВИЕ ТЕМЕ:
        ✅ Иллюстрирует требуемое положение?
        
   3.8. ФАКТИЧЕСКАЯ КОРРЕКТНОСТЬ:
        ✅ Нет фактических ошибок?

КРИТИЧЕСКИЕ ПРАВИЛА: 
- Если пример звучит как "в России...", "многие люди...", "у каждого..." БЕЗ конкретной организации - это НЕ конкретный пример → 0 баллов!
- Если в задании требуется Россия, а пример про "страну Z" → 0 баллов!
- Если требуется структура (элемент → пример), а ее нет → 0 баллов!

═══════════════════════════════════════════════════════════
ФОРМАТ ОТВЕТА (ТОЛЬКО JSON):
═══════════════════════════════════════════════════════════

```json
{{
    "score": число от 0 до 3,
    "valid_examples_count": количество засчитанных конкретных примеров,
    "total_examples": общее количество попыток привести примеры,
    "penalty_applied": true/false,
    "penalty_reason": "причина штрафа" или null,
    
    "task_requirements": {{
        "requires_russia": {str(requires_russia).lower()},
        "requires_structure": {str(bool(structure_type)).lower()},
        "structure_type": "{structure_type if structure_type else 'none'}"
    }},
    
    "valid_examples": [
        {{
            "number": номер примера,
            "text_snippet": "краткая цитата из ответа (до 80 слов)",
            "has_structure": true/false,
            "element": "указанный элемент (функция/мера/процесс)" или null,
            "is_about_russia": true/false/null,
            "why_valid": "почему засчитан: конкретное лицо/организация + конкретная ситуация + детали"
        }}
    ],
    
    "invalid_examples": [
        {{
            "number": номер примера,
            "text_snippet": "краткая цитата из ответа (до 80 слов)",
            "why_invalid": "конкретная причина",
            "violations": {{
                "lacks_concrete_person": true/false,
                "is_abstract": true/false,
                "is_trend_description": true/false,
                "wrong_structure": true/false,
                "not_about_russia": true/false,
                "too_brief": true/false
            }},
            "improvement": "как конкретно исправить этот пример"
        }}
    ],
    
    "feedback": "краткий общий комментарий (2-3 предложения)",
    "suggestions": [
        "конкретная рекомендация 1",
        "конкретная рекомендация 2"
    ],
    "factual_errors": ["ошибка 1"] или []
}}
```

ВАЖНЫЕ ТРЕБОВАНИЯ К JSON:
1. Возвращай ТОЛЬКО валидный JSON в блоке кода ```json
2. Для КАЖДОГО примера укажи "text_snippet" - что именно написал ученик
3. В "why_invalid" пиши КОНКРЕТНО с учетом требований задания
4. Если требуется Россия, а пример НЕ про Россию → укажи "not_about_russia": true
5. Если требуется структура, а ее нет → укажи "wrong_structure": true
6. В "improvement" давай ТОЧНЫЕ советы с учетом требований задания
7. Будь максимально строг к конкретности!"""

        try:
            async with YandexGPTService(self.config) as service:
                result = await service.get_json_completion(
                    prompt=evaluation_prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature,
                )

                if result:
                    return self._parse_response(result, answer, topic, requires_russia, structure_type)

                logger.error("Failed to get JSON response from YandexGPT")
                return self._basic_evaluation(answer, topic)

        except Exception as e:
            logger.error(f"Error in Task19 evaluation: {e}")
            return self._basic_evaluation(answer, topic)
    
    def _parse_response(
        self, 
        ai_result: Dict[str, Any], 
        answer: str, 
        topic: str,
        requires_russia: bool,
        structure_type: Optional[str]
    ) -> EvaluationResult:
        """Парсинг ответа от AI с детальной информацией."""
        try:
            score = int(ai_result.get('score', 0))
            valid_count = ai_result.get('valid_examples_count', 0)
            total_count = ai_result.get('total_examples', 0)
            
            # Формируем обратную связь
            feedback_parts = []
            
            # Требования задания
            task_reqs = ai_result.get('task_requirements', {})
            if requires_russia or structure_type:
                feedback_parts.append("⚠️ Особые требования задания:")
                if requires_russia:
                    feedback_parts.append("   • Примеры ТОЛЬКО про Россию")
                if structure_type:
                    feedback_parts.append("   • Обязательная структура: элемент → пример")
                feedback_parts.append("")
            
            # Общая информация
            feedback_parts.append(f"📊 Обнаружено примеров: {total_count}")
            feedback_parts.append(f"✅ Засчитано конкретных примеров: {valid_count}")
            
            # Штрафы
            if ai_result.get('penalty_applied'):
                penalty_reason = ai_result.get('penalty_reason', 'нарушение требований')
                feedback_parts.append(f"\n⚠️ Применён штраф: {penalty_reason}")
            
            # Детали по засчитанным примерам
            valid_examples = ai_result.get('valid_examples', [])
            if valid_examples:
                feedback_parts.append("\n✅ Засчитанные примеры:")
                for ex in valid_examples[:3]:
                    snippet = ex.get('text_snippet', '')[:100]
                    why_valid = ex.get('why_valid', '')
                    feedback_parts.append(f"\n• Пример {ex['number']}: «{snippet}{'...' if len(ex.get('text_snippet', '')) > 100 else ''}»")
                    if why_valid:
                        feedback_parts.append(f"  ✓ {why_valid}")
            
            # Детали по незасчитанным примерам
            invalid_examples = ai_result.get('invalid_examples', [])
            if invalid_examples:
                feedback_parts.append("\n❌ Не засчитанные примеры:")
                for ex in invalid_examples[:3]:
                    snippet = ex.get('text_snippet', '')[:100]
                    why_invalid = ex.get('why_invalid', '')
                    improvement = ex.get('improvement', '')
                    
                    feedback_parts.append(f"\n• Пример {ex['number']}: «{snippet}{'...' if len(ex.get('text_snippet', '')) > 100 else ''}»")
                    if why_invalid:
                        feedback_parts.append(f"  ✗ {why_invalid}")
                    
                    # Показываем конкретные нарушения
                    violation_details = []
                    if ex.get('not_about_russia'):
                        violation_details.append("не про Россию")
                    if ex.get('wrong_structure'):
                        violation_details.append("неправильная структура")
                    if ex.get('too_abstract'):
                        violation_details.append("слишком абстрактно")
                    if ex.get('lacks_specificity'):
                        violation_details.append("нет конкретики")
                    if ex.get('is_trend_description'):
                        violation_details.append("описание тенденции")
                    
                    if violation_details:
                        feedback_parts.append(f"  ✗ Нарушения: {', '.join(violation_details)}")
                    
                    if improvement:
                        feedback_parts.append(f"  💡 Как исправить: {improvement}")
            
            # Общий комментарий
            if ai_result.get('feedback'):
                feedback_parts.append(f"\n💭 {ai_result['feedback']}")
            
            # Рекомендации
            suggestions = ai_result.get('suggestions', [])
            if suggestions:
                feedback_parts.append("\n📝 Рекомендации:")
                for sug in suggestions[:3]:
                    feedback_parts.append(f"• {sug}")
            
            # Фактические ошибки
            factual_errors = ai_result.get('factual_errors', [])
            if factual_errors:
                feedback_parts.append("\n⚠️ Фактические ошибки:")
                for err in factual_errors:
                    feedback_parts.append(f"• {err}")
            
            feedback = "\n".join(feedback_parts)
            
            # ✅ ИСПРАВЛЕНО: используем criteria_scores и factual_errors
            return EvaluationResult(
                criteria_scores={"К1": score},
                total_score=score,
                max_score=3,
                feedback=feedback,
                suggestions=suggestions,
                factual_errors=factual_errors,
                detailed_feedback=ai_result
            )
            
        except Exception as e:
            logger.error(f"Error parsing AI response: {e}")
            return self._basic_evaluation(answer, topic)
    
    def _basic_evaluation(self, answer: str, topic: str) -> EvaluationResult:
        """Базовая оценка без AI."""
        # Простая проверка наличия примеров
        lines = [line.strip() for line in answer.split('\n') if line.strip()]
        
        # Подсчитываем предложения
        sentences = re.split(r'[.!?]+', answer)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        
        score = min(len(sentences), 3)
        
        # ✅ ИСПРАВЛЕНО: используем criteria_scores и factual_errors
        return EvaluationResult(
            criteria_scores={"К1": score},
            total_score=score,
            max_score=3,
            feedback=f"Базовая оценка: обнаружено {len(sentences)} развёрнутых предложений. "
                    f"Для точной проверки необходима AI-оценка.",
            suggestions=["Используйте конкретные имена и названия", 
                        "Добавляйте детали: кто, что, где, когда",
                        "Соблюдайте структуру ответа, если требуется"],
            factual_errors=[]
        )


# Экспорт для обратной совместимости
__all__ = ['Task19AIEvaluator', 'StrictnessLevel']