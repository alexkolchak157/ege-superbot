"""
Система подсчёта баллов для полного варианта ЕГЭ по обществознанию.

Первичные баллы:
  Часть 1 (задания 1-16):
    - Задания 1, 3, 9, 12 = 1 балл
    - Остальные (2,4,5,6,7,8,10,11,13,14,15,16) = 2 балла
    - Максимум: 4×1 + 12×2 = 28 баллов

  Часть 2 (задания 19-25):
    - Задание 19 = 3 балла
    - Задание 20 = 3 балла
    - Задание 21 = 3 балла
    - Задание 22 = 4 балла
    - Задание 23 = 3 балла
    - Задание 24 = 4 балла
    - Задание 25 = 6 балла
    - Максимум: 26 баллов

  Итого: 54 первичных балла
"""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Задания тестовой части, за которые ставится 1 балл
ONE_POINT_TASKS = {1, 3, 9, 12}

# Максимальные баллы за задания второй части
PART2_MAX_SCORES: Dict[int, int] = {
    19: 3,
    20: 3,
    21: 3,
    22: 4,
    23: 3,
    24: 4,
    25: 6,
}

MAX_PART1_SCORE = 28
MAX_PART2_SCORE = 26
MAX_TOTAL_SCORE = MAX_PART1_SCORE + MAX_PART2_SCORE  # 54

# Шкала перевода первичных баллов во вторичные (2025)
# Источник: шкала ФИПИ для ЕГЭ по обществознанию
PRIMARY_TO_SECONDARY: Dict[int, int] = {
    0: 0, 1: 2, 2: 4, 3: 6, 4: 8, 5: 10,
    6: 12, 7: 14, 8: 16, 9: 18, 10: 20,
    11: 22, 12: 24, 13: 26, 14: 28, 15: 30,
    16: 32, 17: 34, 18: 36, 19: 38, 20: 40,
    21: 42, 22: 44, 23: 45, 24: 46, 25: 47,
    26: 48, 27: 49, 28: 50, 29: 51, 30: 52,
    31: 53, 32: 54, 33: 55, 34: 56, 35: 57,
    36: 59, 37: 61, 38: 63, 39: 65, 40: 67,
    41: 69, 42: 71, 43: 73, 44: 75, 45: 77,
    46: 79, 47: 81, 48: 83, 49: 85, 50: 87,
    51: 89, 52: 91, 53: 95, 54: 100,
}

# Пороговый балл для сдачи (минимальный вторичный)
MIN_PASSING_SECONDARY = 42
MIN_PASSING_PRIMARY = 21


def get_max_score_for_task(exam_number: int) -> int:
    """Максимальный первичный балл за задание."""
    if 1 <= exam_number <= 16:
        return 1 if exam_number in ONE_POINT_TASKS else 2
    return PART2_MAX_SCORES.get(exam_number, 0)


def calculate_part1_score(answers: Dict[int, bool]) -> Tuple[int, int]:
    """
    Подсчёт баллов тестовой части.

    Args:
        answers: {exam_number: is_correct} для заданий 1-16

    Returns:
        (набранные баллы, максимум)
    """
    score = 0
    for exam_num in range(1, 17):
        if answers.get(exam_num, False):
            score += get_max_score_for_task(exam_num)
    return score, MAX_PART1_SCORE


def calculate_part2_score(scores: Dict[int, int]) -> Tuple[int, int]:
    """
    Подсчёт баллов второй части.

    Args:
        scores: {task_number: набранные_баллы} для заданий 19-25

    Returns:
        (набранные баллы, максимум)
    """
    total = 0
    for task_num, max_score in PART2_MAX_SCORES.items():
        earned = scores.get(task_num, 0)
        total += min(earned, max_score)
    return total, MAX_PART2_SCORE


def primary_to_secondary(primary: int) -> int:
    """Перевод первичных баллов во вторичные по шкале ФИПИ."""
    primary = max(0, min(primary, MAX_TOTAL_SCORE))
    return PRIMARY_TO_SECONDARY.get(primary, 0)


def get_grade_description(secondary: int) -> Tuple[str, str]:
    """
    Оценка результата по вторичным баллам.

    Returns:
        (emoji, текст описания)
    """
    if secondary >= 80:
        return "🏆", "Отличный результат! Вы отлично подготовлены к экзамену!"
    elif secondary >= 60:
        return "👍", "Хороший результат! Продолжайте в том же духе."
    elif secondary >= MIN_PASSING_SECONDARY:
        return "📚", "Неплохо, но есть над чем поработать."
    else:
        return "💪", "Требуется дополнительная подготовка. Не сдавайтесь!"


def format_results_summary(
    part1_answers: Dict[int, bool],
    part2_scores: Dict[int, int],
) -> str:
    """Формирует текстовую сводку результатов варианта."""
    p1_score, p1_max = calculate_part1_score(part1_answers)
    p2_score, p2_max = calculate_part2_score(part2_scores)
    total_primary = p1_score + p2_score
    secondary = primary_to_secondary(total_primary)
    emoji, description = get_grade_description(secondary)

    lines = [
        f"{emoji} <b>РЕЗУЛЬТАТЫ ВАРИАНТА ЕГЭ</b>\n",
        f"<b>Часть 1 (тестовая):</b> {p1_score}/{p1_max}",
    ]

    # Детализация по заданиям части 1
    part1_details = []
    for num in range(1, 17):
        max_s = get_max_score_for_task(num)
        if num in part1_answers:
            earned = max_s if part1_answers[num] else 0
            icon = "✅" if part1_answers[num] else "❌"
        else:
            earned = 0
            icon = "⏭️"
        part1_details.append(f"  №{num}: {icon} {earned}/{max_s}")
    lines.append("\n".join(part1_details))

    lines.append(f"\n<b>Часть 2 (развёрнутая):</b> {p2_score}/{p2_max}")

    # Детализация по заданиям части 2
    task_names = {
        19: "Примеры", 20: "Суждения", 21: "Графики",
        22: "Анализ ситуаций", 23: "Конституция",
        24: "Сложный план", 25: "Обоснование",
    }
    for num in sorted(PART2_MAX_SCORES):
        max_s = PART2_MAX_SCORES[num]
        earned = part2_scores.get(num, 0)
        name = task_names.get(num, f"Задание {num}")
        bar = "█" * earned + "░" * (max_s - earned)
        lines.append(f"  №{num} ({name}): {bar} {earned}/{max_s}")

    lines.append("")
    lines.append(
        f"<b>Первичный балл:</b> {total_primary}/{MAX_TOTAL_SCORE}\n"
        f"<b>Вторичный балл:</b> {secondary}/100\n"
    )
    lines.append(description)

    passed = secondary >= MIN_PASSING_SECONDARY
    if passed:
        lines.append(f"\n✅ Порог сдачи ({MIN_PASSING_SECONDARY} баллов) пройден")
    else:
        lines.append(
            f"\n⚠️ Порог сдачи ({MIN_PASSING_SECONDARY} баллов) не пройден "
            f"(не хватает {MIN_PASSING_SECONDARY - secondary} б.)"
        )

    return "\n".join(lines)
