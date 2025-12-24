"""
Загрузчик конкретных вопросов из модулей для выполнения домашних заданий.
"""

import json
import os
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def load_question_by_id(task_module: str, question_id) -> Optional[Dict]:
    """
    Загружает конкретный вопрос по ID из указанного модуля.

    Args:
        task_module: Название модуля ('test_part', 'task19', 'task20', 'task24', 'task25')
        question_id: ID вопроса (может быть строкой для test_part или числом для остальных)

    Returns:
        Словарь с данными вопроса или None если не найден
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

        # Специальная обработка для test_part
        if task_module == 'test_part':
            return _load_test_part_question(question_id, base_dir)

        # Специальная обработка для task24
        if task_module == 'task24':
            return _load_task24_question(question_id, base_dir)

        # Обработка для остальных модулей
        topics_file = os.path.join(base_dir, task_module, f"{task_module}_topics.json")

        if not os.path.exists(topics_file):
            logger.warning(f"Topics file not found: {topics_file}")
            return None

        with open(topics_file, 'r', encoding='utf-8') as f:
            topics = json.load(f)

        # Ищем вопрос по ID
        for topic in topics:
            if topic.get('id') == question_id:
                return topic

        logger.warning(f"Question {question_id} not found in {task_module}")
        return None

    except Exception as e:
        logger.error(f"Error loading question {question_id} from {task_module}: {e}")
        return None


def _load_task24_question(question_id: int, base_dir: str) -> Optional[Dict]:
    """
    Загружает вопрос task24 из plans_data_with_blocks.json.

    Args:
        question_id: ID темы
        base_dir: Базовая директория проекта

    Returns:
        Словарь с данными плана или None
    """
    try:
        plans_file = os.path.join(base_dir, 'data', 'plans_data_with_blocks.json')

        if not os.path.exists(plans_file):
            logger.warning(f"Plans file not found: {plans_file}")
            return None

        with open(plans_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Создаем маппинг ID -> название темы (как в topics_loader)
        topic_id_to_name = {}
        topic_id_counter = 1

        for block_name, topic_names in data.get('blocks', {}).items():
            for topic_name in topic_names:
                topic_id_to_name[topic_id_counter] = topic_name
                topic_id_counter += 1

        # Получаем название темы по ID
        topic_name = topic_id_to_name.get(question_id)
        if not topic_name:
            logger.warning(f"Topic ID {question_id} not found in task24")
            return None

        # Получаем данные плана
        plan_data = data.get('plans', {}).get(topic_name)
        if not plan_data:
            logger.warning(f"Plan data not found for topic: {topic_name}")
            return None

        # Формируем объект вопроса
        return {
            'id': question_id,
            'title': topic_name,
            'block': plan_data.get('block', 'Без категории'),
            'full_plan': plan_data.get('full_plan'),
            'points_data': plan_data.get('points_data'),
            'min_points': plan_data.get('min_points'),
            'min_detailed_points': plan_data.get('min_detailed_points'),
            'min_subpoints': plan_data.get('min_subpoints')
        }

    except Exception as e:
        logger.error(f"Error loading task24 question {question_id}: {e}")
        return None


def _load_test_part_question(question_id: str, base_dir: str) -> Optional[Dict]:
    """
    Загружает вопрос test_part из questions.json через модуль test_part.loader.

    Args:
        question_id: ID вопроса (строка, например "ekonomika_2_1_q1")
        base_dir: Базовая директория проекта

    Returns:
        Словарь с данными вопроса или None
    """
    try:
        # Импортируем функции из test_part
        try:
            from test_part.loader import get_questions_dict_flat, load_questions
        except ImportError:
            # Добавляем в sys.path если не получилось импортировать
            import sys
            test_part_dir = os.path.join(base_dir, 'test_part')
            if test_part_dir not in sys.path:
                sys.path.insert(0, test_part_dir)
            from test_part.loader import get_questions_dict_flat, load_questions

        # Получаем словарь вопросов
        questions_dict = get_questions_dict_flat()

        # Если вопросы не загружены, пытаемся загрузить
        if not questions_dict:
            logger.warning("test_part questions not initialized, attempting to load...")
            load_questions()
            questions_dict = get_questions_dict_flat()

        if not questions_dict:
            logger.warning("No questions available for test_part after load attempt")
            return None

        # Получаем вопрос по ID
        question = questions_dict.get(question_id)

        if not question:
            logger.warning(f"Question {question_id} not found in test_part")
            return None

        return question

    except Exception as e:
        logger.error(f"Error loading test_part question {question_id}: {e}")
        import traceback
        traceback.print_exc()
        return None


def format_question_for_display(task_module: str, question_data: Dict) -> str:
    """
    Форматирует вопрос для отображения ученику.

    Args:
        task_module: Название модуля
        question_data: Данные вопроса из load_question_by_id

    Returns:
        Отформатированный текст вопроса
    """
    if task_module == 'test_part':
        # Используем функцию форматирования из модуля test_part
        try:
            from test_part.utils import format_question_text
            return format_question_text(question_data)
        except ImportError:
            logger.warning("Could not import format_question_text from test_part")
            # Простое форматирование как fallback
            return f"<b>Вопрос #{question_data.get('exam_number', '?')}</b>\n\n{question_data.get('question', str(question_data))}"

    elif task_module == 'task19':
        return f"<b>{question_data['title']}</b>\n\n{question_data['task_text']}"

    elif task_module == 'task20':
        return f"<b>{question_data['title']}</b>\n\n{question_data['task_text']}"

    elif task_module == 'task24':
        text = f"<b>{question_data['title']}</b>\n\n"
        text += "Составьте детализированный план по данной теме.\n\n"
        text += f"<b>Требования:</b>\n"
        text += f"• Минимум {question_data.get('min_points', 3)} пунктов\n"
        text += f"• Минимум {question_data.get('min_detailed_points', 2)} детализированных пунктов\n"
        text += f"• Минимум {question_data.get('min_subpoints', 3)} подпунктов в детализированных пунктах"
        return text

    elif task_module == 'task25':
        parts = question_data.get('parts', {})
        text = f"<b>{question_data['title']}</b>\n\n"
        text += f"<b>Часть 1:</b>\n{parts.get('part1', '')}\n\n"
        text += f"<b>Часть 2:</b>\n{parts.get('part2', '')}\n\n"
        text += f"<b>Часть 3:</b>\n{parts.get('part3', '')}"
        return text

    return str(question_data)
