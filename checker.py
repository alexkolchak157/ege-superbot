import re
import math
import html
import logging
from typing import List, Tuple, Dict, Any, Optional, Set
from collections import defaultdict
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


class PlanBotData:
    def __init__(self, data: Dict[str, Any]):
        logger.info(">>> Вход в PlanBotData.__init__")
        self._morph = None
        self.topics_by_block: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
        self.topic_list_for_pagination: List[Tuple[int, str]] = []
        self.topic_index_map: Dict[int, str] = {}
        self.plans_data: Dict[str, Dict[str, Any]] = {}

        self._load_data(data)
        logger.info("<<< Выход из PlanBotData.__init__")

    def _load_data(self, data: Dict[str, Any]):
        """
        Загружает и обрабатывает данные плана:
        - поддерживает как формат {"plans": {...}, "blocks": {...}}, так и список тем [{...}, ...]
        - наполняет self.plans_data, self.topics_by_block, self.topic_list_for_pagination, self.topic_index_map
        """
        try:
            # --- Если data это список (старый формат) ---
            if isinstance(data, list):
                logger.warning("PlanBotData: data - это список, преобразую в структуру plans и blocks")
                raw_plans = {}
                blocks = {}
                topics = []
                # Каждый элемент списка — это тема (dict: {topic: {поля}})
                for obj in data:
                    if isinstance(obj, dict):
                        for topic, plan_data in obj.items():
                            raw_plans[topic] = plan_data
                            topics.append(topic)
                            # Блоки могут быть внутри plan_data
                            block = plan_data.get("block", "Без блока")
                            blocks.setdefault(block, []).append(topic)
                data = {"plans": raw_plans, "blocks": blocks}
            # --- Если data это словарь ---
            raw_plans = data.get("plans", {})
            if not isinstance(raw_plans, dict):
                logger.error(f"Ключ 'plans' должен быть словарём, но получен {type(raw_plans)}; сбрасываем в {{}}.")
                raw_plans = {}
            self.plans_data = raw_plans

            # 2. Обрабатываем блоки тем (pagination)
            blocks = data.get("blocks", {})
            if not isinstance(blocks, dict):
                logger.error(f"Ключ 'blocks' должен быть словарём, но получен {type(blocks)}; сброс.")
                blocks = {}

            # Очистим коллекции на всякий случай
            self.topics_by_block.clear()
            self.topic_list_for_pagination.clear()
            self.topic_index_map.clear()

            # Наполняем индексы тем
            idx = 0
            for block, topics in blocks.items():
                if not isinstance(topics, list):
                    logger.warning(f"Для блока {block} ожидается список, получен {type(topics)}; пропускаем.")
                    continue
                for topic in topics:
                    self.topics_by_block[block].append((idx, topic))
                    self.topic_list_for_pagination.append((idx, topic))
                    self.topic_index_map[idx] = topic
                    idx += 1

            logger.info(f"Loaded {len(self.topic_list_for_pagination)} topics from blocks.")

        except Exception as e:
            logger.error(f"Ошибка при инициализации PlanBotData: {e}", exc_info=True)
            # Обнуляем всё, чтобы не было непредвиденного поведения
            self.plans_data = {}
            self.topics_by_block.clear()
            self.topic_list_for_pagination.clear()
            self.topic_index_map.clear()
        finally:
            logger.info("<<< Выход из PlanBotData._load_data")


    # Пример метода для получения списка всех тем (зависит от логики _load_data)
    def get_all_topics_list(self) -> List[Tuple[int, str]]:
        """
        Возвращает полный список (index, topic) для постраничного просмотра.
        """
        return self.topic_list_for_pagination


    # Пример метода для получения данных по конкретной теме
    def get_plan_data(self, topic_name):
        # Теперь использует self.plans_data, который был обработан в _load_data
        return self.plans_data.get(topic_name)
        
    def lemmatize_text(self, text: str) -> List[str]:
        if not self._morph:
            logger.error("MorphAnalyzer недоступен для лемматизации текста.")
            return re.findall(r'\b\w+\b', text.lower())
# 2) Парсинг и оценка плана:
def parse_user_plan(text: str) -> List[Tuple[str, List[str]]]:
    parsed_plan = []
    current_point_text = None
    current_subpoints = []
    point_pattern = re.compile(r"^\s*(\d+)[\.\)\-]\s*(.*)")
    subpoint_pattern = re.compile(r"^\s*(?:([а-яa-z])[\.\)]|([*\-]))\s*(.*)")
    lines = text.strip().split('\n')
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line: continue
        point_match = point_pattern.match(stripped_line)
        subpoint_match = subpoint_pattern.match(stripped_line)
        if point_match:
            if current_point_text is not None:
                parsed_plan.append((current_point_text, current_subpoints))
            current_point_text = point_match.group(2).strip()
            current_subpoints = []
            logger.debug(f"Распарсен пункт: {point_match.group(1)}. Текст: '{current_point_text}'")
        elif subpoint_match and current_point_text is not None:
            subpoint_text = subpoint_match.group(3).strip()
            if subpoint_text:
                current_subpoints.append(subpoint_text)
                marker = subpoint_match.group(1) or subpoint_match.group(2)
                logger.debug(f"Распарсен подпункт ({marker}): '{subpoint_text}'")
            else:
                logger.debug(f"Пропущен пустой подпункт: {stripped_line}")
        elif current_point_text is not None and stripped_line: # Добавляем только непустые строки
            # Добавляем продолжение пункта с новой строки
            current_point_text += " " + stripped_line
            logger.debug(f"Строка '{stripped_line}' добавлена к тексту пункта: '{current_point_text}'")
        else:
            logger.debug(f"Игнорируется строка до первого пункта: '{stripped_line}'")
    if current_point_text is not None:
        parsed_plan.append((current_point_text, current_subpoints))
    if not parsed_plan and text.strip():
         logger.warning(f"Не удалось распознать структуру плана пользователя:\n{text[:200]}...")
    return parsed_plan

def _check_plan_structure(parsed_plan: List[Tuple[str, List[str]]], ideal_plan_data: dict) -> Tuple[int, int, int, int]:
    num_user_points = len(parsed_plan)
    detailed_points_count = 0
    detailed_points_with_enough_subpoints = 0
    subpoints_low_count = 0

    for _, subpoints in parsed_plan:
        num_subpoints = len(subpoints)
        if num_subpoints > 0:
             detailed_points_count += 1
             if num_subpoints >= ideal_plan_data.get("min_subpoints", 3):
                  detailed_points_with_enough_subpoints += 1
             elif num_subpoints > 0 : # Подсчет пунктов с 1-2 подпунктами
                  subpoints_low_count += 1

    return num_user_points, detailed_points_count, detailed_points_with_enough_subpoints, subpoints_low_count


def _check_plan_keywords(user_plan_text: str, ideal_plan_data: dict, bot_data: PlanBotData) -> Tuple[int, List[str], List[str]]:
    """Проверяет наличие ключевых слов из эталонного плана в плане пользователя."""
    ideal_points = ideal_plan_data.get("points_data", [])
    num_found_key = 0
    hit_details = []  # Найденные совпадения
    missed_points_details = []  # Не найденные обязательные
    error_feedback = []

    user_plan_lemmas_set = set(bot_data.lemmatize_text(user_plan_text))
    if not user_plan_lemmas_set:
        logger.warning("Не удалось извлечь леммы из плана пользователя.")
        error_feedback.append("⚠️ Не удалось обработать текст вашего плана для поиска ключевых слов.")
        return 0, [], error_feedback

    num_potentially_key_ideal = sum(1 for p in ideal_points if isinstance(p, dict) and p.get("is_potentially_key"))

    for ideal_point_data in ideal_points:
        if not isinstance(ideal_point_data, dict):
            logger.warning(f"Элемент в 'points_data' не является словарем: {ideal_point_data}")
            continue

        ideal_point_text = ideal_point_data.get('point_text', 'Неизвестный пункт')
        lemmatized_keywords = ideal_point_data.get('lemmatized_keywords', [])
        is_key = ideal_point_data.get("is_potentially_key", False)

        if not lemmatized_keywords:
            if is_key:
                missed_points_details.append(f"❓ Пункт <i>{ideal_point_text}</i> (ключевой): Нет слов для автопроверки.")
            continue

        num_keywords = len(lemmatized_keywords)
        required_matches = (
            1 if num_keywords <= 2 else
            2 if num_keywords <= 5 else
            max(2, math.ceil(num_keywords * 0.4))
        )

        matches_count = 0
        found_kws_in_point = []
        for lemma_kw in lemmatized_keywords:
            if lemma_kw in user_plan_lemmas_set:
                matches_count += 1
                found_kws_in_point.append(lemma_kw)

        if matches_count >= required_matches:
            mark = "✅" if is_key else "ℹ️"
            status_text = "обязательный" if is_key else "необязательный"
            hit_details.append(
                f"{mark} Пункт <i>{ideal_point_text}</i> ({status_text}): Найдено слов: {matches_count}/{num_keywords} (требуется ≥ {required_matches})"
            )
            if is_key:
                num_found_key += 1
        elif is_key:
            reason = (
                f"найдено {matches_count} < {required_matches} ключ. слов"
                if matches_count > 0
                else "ключевые слова не найдены"
            )
            missed_points_details.append(
                f"⚠️ Пункт <i>{ideal_point_text}</i> (обязательный): Не засчитан ({reason})"
            )
            logger.debug(f"Пункт '{ideal_point_text}' не засчитан (надо ≥ {required_matches}, найдено {matches_count}: {found_kws_in_point})")

    keyword_feedback = [
        f"<b>🔑 Обнаружено совпадений с ОБЯЗАТЕЛЬНЫМИ пунктами:</b> "
        f"{num_found_key} из {num_potentially_key_ideal}"
    ]

    if hit_details:
        keyword_feedback.append("<b>Найденные совпадения с пунктами эталона:</b>")
        keyword_feedback.extend([f"▫️ {detail}" for detail in hit_details])
    if missed_points_details:
        keyword_feedback.append("<b>Не засчитанные обязательные пункты эталона:</b>")
        keyword_feedback.extend([f"▫️ {detail}" for detail in missed_points_details])

    return num_found_key, keyword_feedback, error_feedback



def _calculate_score(num_user_points: int, detailed_points_count: int, detailed_points_with_enough_subpoints: int, num_found_key: int, ideal_plan_data: dict) -> Tuple[int, int, List[str]]:
    """Рассчитывает баллы К1 и К2 на основе структурного и содержательного анализа."""
    k1_score = 0
    k2_score = 0
    score_explanation = []

    min_points_required = ideal_plan_data.get("min_points", 3)
    min_detailed_points_required = ideal_plan_data.get("min_detailed_points", 2)
    min_subpoints_req = ideal_plan_data.get("min_subpoints", 3)

    has_min_points = num_user_points >= min_points_required
    has_min_detailed = detailed_points_with_enough_subpoints >= min_detailed_points_required
    has_one_detailed_enough = detailed_points_with_enough_subpoints >= 1
    has_at_least_one_detailed = detailed_points_count >= 1
    key_points_sufficient = num_found_key >= min_detailed_points_required

    if has_min_points and has_min_detailed and key_points_sufficient:
        k1_score = 3
        score_explanation.append(f"✅ Структура: {num_user_points} п. (≥{min_points_required}), из них {detailed_points_with_enough_subpoints} детализированы {min_subpoints_req}+ подпунктами (≥{min_detailed_points_required}).")
        score_explanation.append(f"✅ Содержание: Найдено {num_found_key} обяз. пунктов по словам (≥{min_detailed_points_required}, достаточно).")
    elif has_min_points and key_points_sufficient and (not has_min_detailed and has_one_detailed_enough):
        k1_score = 2
        score_explanation.append(f"⚠️ Структура: {num_user_points} п. (≥{min_points_required}), но только {detailed_points_with_enough_subpoints} детализирован(ы) {min_subpoints_req}+ подпунктами (<{min_detailed_points_required}).")
        score_explanation.append(f"✅ Содержание: Найдено {num_found_key} обяз. пунктов по словам (≥{min_detailed_points_required}, достаточно).")
    elif has_min_points and has_min_detailed and not key_points_sufficient:
        k1_score = 2
        score_explanation.append(f"✅ Структура: {num_user_points} п. (≥{min_points_required}), {detailed_points_with_enough_subpoints} детализированы {min_subpoints_req}+ подпунктами (≥{min_detailed_points_required}).")
        score_explanation.append(f"⚠️ Содержание: Найдено {num_found_key} обяз. пунктов по словам (<{min_detailed_points_required}, недостаточно).")
    elif has_min_points and has_at_least_one_detailed and key_points_sufficient and not has_one_detailed_enough:
        k1_score = 1
        score_explanation.append(f"⚠️ Структура: {num_user_points} п. (≥{min_points_required}), но {detailed_points_with_enough_subpoints} детализирован(ы) {min_subpoints_req}+ подпунктами (=0).")
        score_explanation.append(f"✅ Содержание: Найдено {num_found_key} обяз. пунктов по словам (≥{min_detailed_points_required}, достаточно).")
    else:
        k1_score = 0
        struct_issue = ""
        if not has_min_points: struct_issue += f"менее {min_points_required} п.; "
        if not has_min_detailed: struct_issue += f"менее {min_detailed_points_required} детализир. {min_subpoints_req}+ подп.; "
        content_issue = f"найдено {num_found_key} (<{min_detailed_points_required}) обяз. пунктов" if not key_points_sufficient else ""
        score_explanation.append(f"❌ План не соответствует критериям К1 ({struct_issue.strip()}; {content_issue})")

    if k1_score == 3:
        k2_score = 1
        score_explanation.append("✅ Корректность (К2): +1 балл (выставляется при К1=3). Бот не проверяет ошибки/неточности в тексте.")
    else:
        k2_score = 0
        score_explanation.append("➖ Корректность (К2): 0 баллов (т.к. К1 < 3).")

    return k1_score, k2_score, score_explanation


def _format_evaluation_feedback(k1: int, k2: int, score_explanation: List[str], structure_feedback: List[str], keyword_feedback: List[str], error_feedback: List[str], topic_name: str) -> str:
    """Форматирует итоговое сообщение с использованием HTML."""
    total_score = k1 + k2
    escaped_topic_name = html.escape(str(topic_name)) if topic_name else "Неизвестная тема"
    score_emoji = "🎉" if total_score == 4 else "👍" if total_score == 3 else "🤔" if total_score > 0 else "🙁"

    feedback = [f"📌 <b>Тема:</b> {escaped_topic_name}\n"]
    feedback.append(f"{score_emoji} <b>Предположительная оценка: {total_score} из 4</b> {score_emoji}")
    feedback.append(f"  К1 (Раскрытие темы): <b>{k1} / 3</b>")
    feedback.append(f"  К2 (Корректность):    <b>{k2} / 1</b>") # Выравнивание пробелами

    if score_explanation:
        feedback.append("\n  📝 <b>Пояснения к баллам К1:</b>")
        feedback.extend([f"      - {exp}" for exp in score_explanation])

    important_note = "<i>❗️ Важно: Оценка приблизительная. Бот не заменяет эксперта ЕГЭ и не проверяет корректность формулировок (К2).</i>"
    feedback.append(f"\n  {important_note}")
    feedback.append("\n------------------------------------\n")
    feedback.append("🔍 <b>Детальный анализ:</b>\n")

    if error_feedback:
        feedback.append("<b>🚫 Ошибки анализа:</b>")
        feedback.extend([f"    - {err}" for err in error_feedback])
        feedback.append("")

    if structure_feedback:
        header = html.escape(structure_feedback[0].replace('* **','').replace('**','').strip())
        feedback.append(f"🏗️ {structure_feedback[0]}")  # Уже содержит <b>...</b>
        feedback.extend([f"    {line.strip()}" for line in structure_feedback[1:]])
        feedback.append("")

    if keyword_feedback:
        keyword_headers = {
            "Обнаружено совпадений с ОБЯЗАТЕЛЬНЫМИ пунктами:",
            "Найденные совпадения с пунктами эталона:",
            "Не засчитанные обязательные пункты эталона:"
        }
        first_item_in_list = True
        for i, line in enumerate(keyword_feedback):
            line_stripped = line.strip()
            cleaned_line = line_stripped.replace("* **", "").replace("**", "").strip()
            is_header = any(cleaned_line.startswith(html.escape(h)) for h in keyword_headers) or (i==0 and "Обнаружено совпадений" in cleaned_line)

            if is_header:
                if not first_item_in_list: feedback.append("")
                feedback.append(f"🔑 <b>{cleaned_line}</b>")
                first_item_in_list = True
            elif line_stripped:
                feedback.append(f"    {cleaned_line}") # Отступ для элементов списка
                first_item_in_list = False

    return "\n".join(feedback)

def evaluate_plan(
    user_plan_text: str,
    ideal_plan_data: dict,
    bot_data: PlanBotData,
    topic_name: str
) -> str:
    """
    Разбирает и оценивает пользовательский план:
     1) проверяет структуру (пункты/подпункты);
     2) ищет ключевые слова;
     3) вычисляет баллы K1 и K2;
     4) собирает и возвращает HTML-фидбек.
    """
    # 0. Парсим план
    parsed = parse_user_plan(user_plan_text)
    if not parsed and user_plan_text.strip():
        return "<b>Ошибка разбора плана!</b> Проверьте формат нумерации."
    if not parsed:
        return "Пустой план. Пришлите, пожалуйста, ваш вариант."

    # 1. Структура
    pts, det_cnt, det_enough_cnt, det_low_cnt = _check_plan_structure(
        parsed, ideal_plan_data
    )
    # Собираем пояснения по структуре
    struct_fb = [
        f"• Всего пунктов: {pts}",
        f"• Детализированных пунктов: {det_cnt}",
        f"• Пунктов с достаточным числом подпунктов: {det_enough_cnt}",
        f"• Пунктов с недостаточным числом подпунктов: {det_low_cnt}"
    ]

    # 2. Ключевые слова
    found_key, keyword_fb, error_fb = _check_plan_keywords(
        user_plan_text, ideal_plan_data, bot_data
    )

    # 3. Считаем баллы
    k1, k2, score_expl = _calculate_score(
        pts, det_cnt, det_enough_cnt, found_key, ideal_plan_data
    )

    # 4. Формируем итоговый фидбек
    feedback = _format_evaluation_feedback(
        k1=k1,
        k2=k2,
        score_explanation=score_expl,
        structure_feedback=struct_fb,
        keyword_feedback=keyword_fb,
        error_feedback=error_fb,
        topic_name=topic_name
    )

    return feedback

# ——————————————————————————————————————————————————————————
# 3) Inline-клавиатура для фидбека
FEEDBACK_KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🏠 Главное меню", callback_data="back_main"),
        InlineKeyboardButton("➡️ Продолжить",   callback_data="next_topic")
    ]
])
