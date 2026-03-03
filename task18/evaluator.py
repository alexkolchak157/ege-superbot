"""AI-проверка для задания 18 ЕГЭ по обществознанию.

Задание 18 — признаки понятия + объяснение связи с текстом.
Максимальный балл — 2.

Ответ оценивается по ДВУМ элементам:
  Элемент 1: Признаки понятия (≥3, минимум 2 из эталонного перечня,
             без неверных позиций).
  Элемент 2: Объяснение связи характеристики/функции из текста
             с более широким явлением (каузальная/функциональная связь).
             Для элемента 2 требуется опора на ответ задания 17 (текст).

Критерии оценивания (ФИПИ, методические рекомендации для экспертов):
  2 балла — оба элемента верны.
  1 балл  — верен только один из двух элементов.
  0 баллов — оба элемента неверны / рассуждения общего характера /
             неверный ответ.
"""

import json
import logging
import os
from typing import Dict, List, Any, Optional

from core.types import TaskRequirements, EvaluationResult

logger = logging.getLogger(__name__)

try:
    from core.ai_service import create_ai_service, AIServiceConfig, AIModel
    AI_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI service not available: {e}")
    AI_AVAILABLE = False


# ------------------------------------------------------------------
# Загрузка каталога признаков
# ------------------------------------------------------------------

_katalog_data: Optional[Dict[str, Any]] = None


def _load_katalog() -> Dict[str, Any]:
    """Загрузить каталог признаков из JSON."""
    global _katalog_data
    if _katalog_data is not None:
        return _katalog_data

    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(base_dir, "data", "katalog_priznakov.json")
        with open(path, "r", encoding="utf-8") as f:
            _katalog_data = json.load(f)
            count = len(_katalog_data.get("terms", []))
            logger.info(f"Loaded katalog_priznakov.json: {count} terms")
    except Exception as e:
        logger.error(f"Failed to load katalog_priznakov.json: {e}")
        _katalog_data = {"terms": []}

    return _katalog_data


def find_catalog_signs(concept: str) -> List[str]:
    """Найти признаки понятия в каталоге по ключевому слову."""
    katalog = _load_katalog()
    concept_lower = concept.lower().strip()

    # Точное совпадение
    for entry in katalog.get("terms", []):
        if entry["term"].lower() == concept_lower:
            return entry["signs"]

    # Поиск по вхождению
    matches = []
    for entry in katalog.get("terms", []):
        term = entry["term"].lower()
        if concept_lower in term or term in concept_lower:
            matches.append(entry)

    if matches:
        # Предпочитаем наиболее близкое совпадение (по длине)
        matches.sort(key=lambda e: abs(len(e["term"]) - len(concept)))
        return matches[0]["signs"]

    return []


class Task18AIEvaluator:
    """AI-проверщик для задания 18."""

    def __init__(self):
        self.requirements = TaskRequirements(
            task_number=18,
            task_name="Анализ текста: объяснение понятия",
            max_score=2,
            criteria=[],
            description=(
                "Используя обществоведческие знания, объясните понятие "
                "из текста и/или приведите примеры, признаки, функции."
            ),
        )
        self.config = None
        if AI_AVAILABLE:
            try:
                self.config = AIServiceConfig.from_env()
                self.config.model = AIModel.LITE
                self.config.temperature = 0.2
                logger.info("Task18 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI for task18: {e}")

    # ------------------------------------------------------------------
    # system prompt
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return """Ты — опытный эксперт ЕГЭ по обществознанию, проверяющий задание 18.

СУТЬ ЗАДАНИЯ 18:
Ученику дан тот же текстовый фрагмент, что и в задании 17. Задание 18
оценивается по ДВУМ ЭЛЕМЕНТАМ:

ЭЛЕМЕНТ 1 — Признаки понятия:
  Ученик должен назвать не менее 3 признаков указанного понятия,
  из которых минимум 2 должны соответствовать эталонному перечню
  (каталогу признаков).

ЭЛЕМЕНТ 2 — Объяснение связи с текстом:
  Ученик должен объяснить связь между конкретной характеристикой/функцией,
  упомянутой автором в тексте, и более широким явлением. Требуется
  каузальная или функциональная связь, а не простое цитирование.
  При проверке элемента 2 используй ответ ученика на задание 17 как
  контекст, подтверждающий понимание учеником текста.

КРИТЕРИИ ОЦЕНИВАНИЯ (максимум 2 балла):
• 2 балла — оба элемента верны (≥3 признаков + корректное объяснение).
• 1 балл  — верен только ОДИН из двух элементов.
• 0 баллов — оба элемента неверны / рассуждения общего характера /
  неверный ответ.

ВАЖНЫЕ ПРАВИЛА ОЦЕНИВАНИЯ ЭЛЕМЕНТА 1 (Признаки понятия):

1. НЕ ЗАСЧИТЫВАЙ признаки, которые уже содержатся в ФОРМУЛИРОВКЕ
   ЗАДАНИЯ. Например, если задание говорит «налог как законно
   установленный платёж», то «законность» и «платёж физических и
   юридических лиц» НЕ засчитываются как самостоятельные признаки.

2. НЕ ЗАСЧИТЫВАЙ признаки, сформулированные через ОТРИЦАНИЕ
   («не является коммерческим» и т.п.).

3. НЕ ЗАСЧИТЫВАЙ признаки, определённые через ЭТИМОЛОГИЮ СЛОВА,
   МЕТАФОРУ или АЛЛЕГОРИЮ.

4. НЕ ЗАСЧИТЫВАЙ «ПУСТЫЕ» признаки — общие слова без содержания
   («важный», «значимый» и т.п.).

5. ЕСЛИ ЕСТЬ ХОТЯ БЫ ОДНА НЕВЕРНАЯ ПОЗИЦИЯ — весь элемент 1 НЕ
   засчитывается, даже если остальные признаки верны.

6. ЗАСЧИТЫВАЙ близкие по смыслу формулировки — не требуй дословного
   совпадения с эталоном. Разные учебники дают разные определения.

7. Если один признак ДУБЛИРУЕТ другой по смыслу — засчитывается один.

8. Если ученик выписал определение без разбивки на признаки — проверь,
   можно ли выделить из него ≥3 конкретных признака.

9. МИНИМУМ 2 признака из 3+ должны соответствовать эталонному перечню
   (каталогу признаков).

ВАЖНЫЕ ПРАВИЛА ОЦЕНИВАНИЯ ЭЛЕМЕНТА 2 (Объяснение связи):

1. ПРОВЕРЯЙ ОПОРУ НА ТЕКСТ. Ученик должен объяснить связь именно той
   функции/характеристики, которую упоминает АВТОР ТЕКСТА, а не
   произвольной. Сравни с ответом ученика на задание 17, чтобы убедиться,
   что ученик правильно работает с текстом.

2. Должна прослеживаться КАУЗАЛЬНАЯ или ФУНКЦИОНАЛЬНАЯ связь:
   (функция из текста) → (механизм связи) → (влияние на явление).
   Простая констатация без объяснения связи НЕ засчитывается.

3. НЕ ЗАСЧИТЫВАЙ: только общие рассуждения без конкретной связи;
   простое цитирование текста без объяснения причинно-следственных
   связей; объяснение, не привязанное к тексту.

4. ЕСЛИ В ОБЪЯСНЕНИИ ЕСТЬ ОШИБОЧНЫЕ СУЖДЕНИЯ НАРЯДУ С ВЕРНЫМИ —
   элемент 2 НЕ засчитывается.

Отвечай ВСЕГДА в формате JSON."""

    # ------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        answer: str,
        task_data: Dict[str, Any],
        **kwargs,
    ) -> EvaluationResult:
        if not AI_AVAILABLE or not self.config:
            return self._basic_evaluation(answer, task_data)

        prompt = self._build_evaluation_prompt(answer, task_data)

        try:
            async with create_ai_service(self.config) as service:
                result = await service.get_json_completion(
                    prompt=prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature,
                )
                if result:
                    return self._parse_response(result, task_data)
                logger.error("AI returned None for task18")
                return self._basic_evaluation(answer, task_data)
        except Exception as e:
            logger.error(f"Error in Task18 evaluation: {e}")
            return self._basic_evaluation(answer, task_data)

    # ------------------------------------------------------------------
    # prompt builder
    # ------------------------------------------------------------------

    def _build_evaluation_prompt(
        self,
        answer: str,
        task_data: Dict[str, Any],
    ) -> str:
        text = task_data.get("text", "")
        question = task_data.get("question", "")
        concept = task_data.get("concept", "")
        correct_answer = task_data.get("correct_answer", {})
        required_count = correct_answer.get("required_count", 3)
        elements = correct_answer.get("elements", [])
        scoring_notes = task_data.get("scoring_notes", "")
        task17_answer = task_data.get("task17_answer", "")

        correct_block = "\n".join(
            f"  {i}. {e}" for i, e in enumerate(elements, 1)
        )

        # Получить признаки из каталога
        catalog_signs = find_catalog_signs(concept)
        if catalog_signs:
            catalog_block = "\n".join(
                f"  {i}. {s}" for i, s in enumerate(catalog_signs, 1)
            )
        else:
            catalog_block = "  (признаки не найдены в каталоге — опирайся на эталонные ответы)"

        # Блок ответа на задание 17
        task17_block = ""
        if task17_answer:
            task17_block = f"""
ОТВЕТ УЧЕНИКА НА ЗАДАНИЕ 17 (для контекста при проверке элемента 2):
{task17_answer}

ВАЖНО: Используй ответ на задание 17, чтобы проверить, насколько ученик
понимает текст и правильно выделяет функции/характеристики из него.
Если ответ на задание 17 содержит ошибки в работе с текстом, учти это
при оценке элемента 2 задания 18.
"""

        return f"""Проверь ответ на задание 18 ЕГЭ по обществознанию.

ТЕКСТ (тот же, что и в задании 17):
{text}

ВОПРОС:
{question}

КЛЮЧЕВОЕ ПОНЯТИЕ: {concept}

КАТАЛОГ ПРИЗНАКОВ ПОНЯТИЯ «{concept}» (эталонный перечень из методического каталога):
{catalog_block}

ЭТАЛОННЫЕ ОТВЕТЫ (из методических рекомендаций):
{correct_block}

ТРЕБУЕМОЕ КОЛИЧЕСТВО ЭЛЕМЕНТОВ (признаков): {required_count}

ДОПОЛНИТЕЛЬНЫЕ КРИТЕРИИ:
{scoring_notes}
{task17_block}
ОТВЕТ УЧЕНИКА НА ЗАДАНИЕ 18:
{answer}

ПОШАГОВЫЙ АЛГОРИТМ ПРОВЕРКИ:

ШАГ 1: Проверка ЭЛЕМЕНТА 1 (Признаки понятия):
  a) Выдели все заявленные признаки из ответа ученика.
  b) ИСКЛЮЧИ признаки, которые:
     - уже есть в формулировке задания (повторение из условия)
     - сформулированы через отрицание
     - являются метафорой, аллегорией или этимологией слова
     - являются «пустыми» (общие слова без содержания)
     - дублируют другой признак по смыслу
  c) Сопоставь каждый оставшийся признак с КАТАЛОГОМ ПРИЗНАКОВ
     (эталонным перечнем). Засчитывай близкие по смыслу формулировки —
     не требуй дословного совпадения.
  d) ЕСЛИ ЕСТЬ ХОТЯ БЫ ОДНА НЕВЕРНАЯ ПОЗИЦИЯ → элемент 1 = НЕ засчитан.
  e) ЕСЛИ верных ≥ 3 И минимум 2 из каталога признаков → элемент 1 засчитан.

ШАГ 2: Проверка ЭЛЕМЕНТА 2 (Объяснение связи с текстом):
  a) Найди в тексте задания, КАКАЯ конкретно характеристика/функция
     упоминается автором.
  b) Если предоставлен ответ на задание 17, сверь, правильно ли ученик
     работает с текстом (корректно ли выделяет ключевые элементы).
  c) Проверь, ссылается ли объяснение ученика именно на функцию/
     характеристику из текста (не на произвольную).
  d) Проверь наличие каузальной/функциональной связи
     (не просто констатация факта, а объяснение механизма).
  e) Проверь отсутствие ошибочных суждений. Если есть ошибки наряду
     с верными положениями → элемент 2 НЕ засчитан.
  f) Если всё выполнено → элемент 2 засчитан.

ШАГ 3: Итоговый балл:
  - Оба элемента засчитаны → 2 балла
  - Только один элемент засчитан → 1 балл
  - Ни один не засчитан → 0 баллов

Ответь в формате JSON:
```json
{{
    "score": число от 0 до 2,
    "element1_accepted": true/false,
    "element2_accepted": true/false,
    "element1_evaluation": {{
        "traits_found": ["признак 1", "признак 2", ...],
        "traits_excluded": [
            {{"trait": "текст", "reason": "причина исключения"}}
        ],
        "traits_valid_count": число верных признаков,
        "traits_from_standard": число признаков из каталога признаков,
        "has_invalid_traits": true/false,
        "invalid_traits": ["неверный признак 1"],
        "comment": "комментарий по элементу 1"
    }},
    "element2_evaluation": {{
        "text_reference": "какая функция/характеристика из текста использована",
        "task17_consistency": "соответствует ли работа с текстом ответу на задание 17",
        "has_causal_link": true/false,
        "has_text_grounding": true/false,
        "has_errors": true/false,
        "errors_found": ["ошибка 1"],
        "comment": "комментарий по элементу 2"
    }},
    "feedback": "общий комментарий (2-3 предложения)",
    "suggestions": ["рекомендация 1", "рекомендация 2"]
}}
```

ВАЖНО: Верни ТОЛЬКО валидный JSON."""

    # ------------------------------------------------------------------
    # response parsing
    # ------------------------------------------------------------------

    def _parse_response(
        self,
        response: Dict[str, Any],
        task_data: Dict[str, Any],
    ) -> EvaluationResult:
        try:
            score = min(max(response.get("score", 0), 0), 2)
            el1_ok = response.get("element1_accepted", False)
            el2_ok = response.get("element2_accepted", False)

            feedback = response.get("feedback", "")

            # Сводка
            el1_icon = "\u2705" if el1_ok else "\u274c"
            el2_icon = "\u2705" if el2_ok else "\u274c"
            feedback += (
                f"\n\n<b>Результат:</b> Балл: {score}/2\n"
                f"{el1_icon} Элемент 1 (признаки понятия): "
                f"{'засчитан' if el1_ok else 'не засчитан'}\n"
                f"{el2_icon} Элемент 2 (объяснение связи): "
                f"{'засчитано' if el2_ok else 'не засчитано'}\n"
            )

            # Детали по элементу 1
            el1_eval = response.get("element1_evaluation", {})
            if el1_eval:
                feedback += "\n<b>Элемент 1 — Признаки понятия:</b>\n"

                traits = el1_eval.get("traits_found", [])
                valid_count = el1_eval.get("traits_valid_count", 0)
                from_std = el1_eval.get("traits_from_standard", 0)

                if traits:
                    for trait in traits:
                        feedback += f"  \u2022 {trait}\n"

                # Исключённые признаки
                excluded = el1_eval.get("traits_excluded", [])
                if excluded:
                    feedback += "  <i>Исключены:</i>\n"
                    for ex in excluded:
                        t = ex.get("trait", "")
                        r = ex.get("reason", "")
                        feedback += f"  \u2796 {t}"
                        if r:
                            feedback += f" ({r})"
                        feedback += "\n"

                # Неверные
                invalid = el1_eval.get("invalid_traits", [])
                if invalid:
                    feedback += "  <i>Неверные:</i>\n"
                    for inv in invalid:
                        feedback += f"  \u274c {inv}\n"
                    feedback += (
                        "  \u26a0\ufe0f Наличие неверной позиции — "
                        "весь элемент 1 не засчитан.\n"
                    )

                feedback += (
                    f"  Верных: {valid_count}, из каталога признаков: {from_std}\n"
                )

                el1_comment = el1_eval.get("comment", "")
                if el1_comment:
                    feedback += f"  {el1_comment}\n"

            # Детали по элементу 2
            el2_eval = response.get("element2_evaluation", {})
            if el2_eval:
                feedback += "\n<b>Элемент 2 — Объяснение связи:</b>\n"

                text_ref = el2_eval.get("text_reference", "")
                if text_ref:
                    feedback += f"  Привязка к тексту: {text_ref}\n"

                t17_cons = el2_eval.get("task17_consistency", "")
                if t17_cons:
                    feedback += f"  Связь с заданием 17: {t17_cons}\n"

                has_causal = el2_eval.get("has_causal_link", False)
                has_ground = el2_eval.get("has_text_grounding", False)
                has_errors = el2_eval.get("has_errors", False)

                if has_causal:
                    feedback += "  \u2705 Каузальная/функциональная связь: есть\n"
                else:
                    feedback += "  \u274c Каузальная/функциональная связь: нет\n"

                if not has_ground:
                    feedback += "  \u274c Нет опоры на текст\n"

                if has_errors:
                    errors = el2_eval.get("errors_found", [])
                    for err in errors:
                        feedback += f"  \u274c Ошибка: {err}\n"

                el2_comment = el2_eval.get("comment", "")
                if el2_comment:
                    feedback += f"  {el2_comment}\n"

            return EvaluationResult(
                criteria_scores={"K1": score},
                total_score=score,
                max_score=2,
                feedback=feedback,
                detailed_feedback=response,
                suggestions=response.get("suggestions", []),
                factual_errors=[],
            )
        except Exception as e:
            logger.error(f"Error parsing task18 AI response: {e}")
            return self._basic_evaluation("", task_data)

    # ------------------------------------------------------------------
    # fallback
    # ------------------------------------------------------------------

    def _basic_evaluation(
        self,
        answer: str,
        task_data: Dict[str, Any],
    ) -> EvaluationResult:
        return EvaluationResult(
            criteria_scores={"K1": 0},
            total_score=0,
            max_score=2,
            feedback=(
                "AI-сервис временно недоступен. "
                "Обратитесь к преподавателю для проверки."
            ),
            detailed_feedback={},
            suggestions=[
                "Опирайтесь на обществоведческие знания, а не только на текст",
                "Приводите конкретные примеры, а не общие фразы",
            ],
            factual_errors=[],
        )
