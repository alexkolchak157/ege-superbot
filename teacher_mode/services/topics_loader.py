"""
Загрузчик тем из банка заданий для создания домашних заданий.
"""

import json
import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def load_topics_for_module(task_module: str) -> Dict:
    """
    Загружает темы для указанного модуля задания.

    Args:
        task_module: Название модуля ('test_part', 'task19', 'task20', 'task24', 'task25')

    Returns:
        Словарь с темами в формате:
        {
            'blocks': {
                'Блок 1': [{'id': 1, 'title': 'Тема 1'}, ...],
                'Блок 2': [...],
                ...
            },
            'topics_by_id': {1: {...}, 2: {...}, ...},
            'total_count': 120
        }
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

        # Специальная обработка для test_part
        if task_module == 'test_part':
            return _load_test_part_topics(base_dir)

        # Специальная обработка для task24
        if task_module == 'task24':
            return _load_task24_plans(base_dir)

        # Обработка для остальных модулей (task19, task20, task25)
        topics_file = os.path.join(base_dir, task_module, f"{task_module}_topics.json")

        if not os.path.exists(topics_file):
            logger.info(f"Topics file not found for {task_module}: {topics_file}")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        with open(topics_file, 'r', encoding='utf-8') as f:
            raw_topics = json.load(f)

        # Обрабатываем темы
        blocks = {}
        topics_by_id = {}

        for topic in raw_topics:
            topic_id = topic.get('id')
            block_name = topic.get('block', 'Без категории')

            # Добавляем в словарь по ID
            topics_by_id[topic_id] = topic

            # Добавляем в блок
            if block_name not in blocks:
                blocks[block_name] = []

            blocks[block_name].append({
                'id': topic_id,
                'title': topic.get('title', f'Тема {topic_id}')
            })

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': len(raw_topics)
        }

    except Exception as e:
        logger.error(f"Error loading topics for {task_module}: {e}")
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def _load_test_part_topics(base_dir: str) -> Dict:
    """
    Загружает темы для тестовой части (задания 1-16) из questions.json.

    Args:
        base_dir: Базовая директория проекта

    Returns:
        Словарь в формате, совместимом с load_topics_for_module
    """
    try:
        # Пытаемся импортировать напрямую
        try:
            from test_part.loader import get_questions_list_flat, load_questions
        except ImportError:
            # Если не получилось - добавляем в sys.path
            import sys
            test_part_dir = os.path.join(base_dir, 'test_part')
            if test_part_dir not in sys.path:
                sys.path.insert(0, test_part_dir)
                logger.info(f"Added {test_part_dir} to sys.path for test_part import")

            from test_part.loader import get_questions_list_flat, load_questions

        # Получаем список вопросов
        questions = get_questions_list_flat()

        # Если вопросы не загружены (None или пустой список), пытаемся загрузить
        if not questions:
            logger.warning("test_part questions not initialized, attempting to load...")
            try:
                load_questions()  # Принудительная загрузка
                questions = get_questions_list_flat()
            except Exception as load_error:
                logger.error(f"Failed to load test_part questions: {load_error}")

        if not questions:
            logger.warning("No questions available for test_part after load attempt")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        # Группируем вопросы по exam_number (только 1-16 для тестовой части)
        blocks = {}
        topics_by_id = {}
        topic_id_counter = 1

        # Фильтруем вопросы с exam_number от 1 до 16
        test_part_questions = [q for q in questions if q.get('exam_number') and 1 <= q.get('exam_number') <= 16]

        # Группируем по exam_number и по блоку
        from collections import defaultdict
        exam_groups = defaultdict(lambda: defaultdict(list))

        for question in test_part_questions:
            exam_num = question.get('exam_number')
            block = question.get('block', 'Без категории')
            exam_groups[exam_num][block].append(question)

        # Создаем структуру для каждого номера задания
        for exam_num in sorted(exam_groups.keys()):
            block_name = f"Задание {exam_num}"
            blocks[block_name] = []

            # Внутри каждого номера группируем по предметным блокам (Экономика, Политика и т.д.)
            for subject_block, block_questions in sorted(exam_groups[exam_num].items()):
                # Создаем "тему" для каждого предметного блока внутри номера задания
                topic_obj = {
                    'id': topic_id_counter,
                    'exam_number': exam_num,
                    'block': subject_block,
                    'title': f"{subject_block}",
                    'questions_count': len(block_questions),
                    'question_ids': [q['id'] for q in block_questions]
                }

                topics_by_id[topic_id_counter] = topic_obj

                blocks[block_name].append({
                    'id': topic_id_counter,
                    'title': f"{subject_block} ({len(block_questions)} вопросов)"
                })

                topic_id_counter += 1

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': len(test_part_questions)
        }

    except Exception as e:
        logger.error(f"Error loading test_part topics: {e}")
        import traceback
        traceback.print_exc()
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def _load_task24_plans(base_dir: str) -> Dict:
    """
    Загружает планы для task24 из plans_data_with_blocks.json.

    Args:
        base_dir: Базовая директория проекта

    Returns:
        Словарь в формате, совместимом с load_topics_for_module
    """
    try:
        plans_file = os.path.join(base_dir, 'data', 'plans_data_with_blocks.json')

        if not os.path.exists(plans_file):
            logger.info(f"Plans file not found for task24: {plans_file}")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        with open(plans_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        blocks = {}
        topics_by_id = {}
        topic_id_counter = 1

        # Создаем маппинг названия темы -> ID
        topic_name_to_id = {}

        # Обрабатываем блоки
        for block_name, topic_names in data.get('blocks', {}).items():
            blocks[block_name] = []

            for topic_name in topic_names:
                # Присваиваем ID теме
                if topic_name not in topic_name_to_id:
                    topic_name_to_id[topic_name] = topic_id_counter
                    topic_id_counter += 1

                topic_id = topic_name_to_id[topic_name]

                # Получаем данные плана из раздела plans
                plan_data = data.get('plans', {}).get(topic_name, {})

                # Создаем объект темы
                topic_obj = {
                    'id': topic_id,
                    'title': topic_name,
                    'block': block_name,
                    'plan_data': plan_data  # Сохраняем полные данные плана
                }

                topics_by_id[topic_id] = topic_obj

                blocks[block_name].append({
                    'id': topic_id,
                    'title': topic_name
                })

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': len(topics_by_id)
        }

    except Exception as e:
        logger.error(f"Error loading task24 plans: {e}")
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def get_blocks_list(task_module: str) -> List[str]:
    """
    Получает список названий блоков для модуля.

    Args:
        task_module: Название модуля ('task19', 'task20', 'task24', 'task25')

    Returns:
        Список названий блоков
    """
    data = load_topics_for_module(task_module)
    return list(data['blocks'].keys())


def get_topics_in_block(task_module: str, block_name: str) -> List[Dict]:
    """
    Получает список тем в указанном блоке.

    Args:
        task_module: Название модуля
        block_name: Название блока

    Returns:
        Список тем в формате [{'id': 1, 'title': 'Тема'}, ...]
    """
    data = load_topics_for_module(task_module)
    return data['blocks'].get(block_name, [])


def get_topic_by_id(task_module: str, topic_id: int) -> Optional[Dict]:
    """
    Получает тему по её ID.

    Args:
        task_module: Название модуля
        topic_id: ID темы

    Returns:
        Словарь с данными темы или None
    """
    data = load_topics_for_module(task_module)
    return data['topics_by_id'].get(topic_id)


def get_topic_ids_by_blocks(task_module: str, block_names: List[str]) -> List[int]:
    """
    Получает список ID тем для указанных блоков.

    Args:
        task_module: Название модуля
        block_names: Список названий блоков

    Returns:
        Список ID тем
    """
    data = load_topics_for_module(task_module)
    topic_ids = []

    for block_name in block_names:
        topics = data['blocks'].get(block_name, [])
        topic_ids.extend([t['id'] for t in topics])

    return topic_ids


def module_supports_topics(task_module: str) -> bool:
    """
    Проверяет, поддерживает ли модуль систему тем.

    Args:
        task_module: Название модуля ('test_part', 'task19', 'task20', 'task24', 'task25')

    Returns:
        True если модуль имеет файл с темами
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    # test_part поддерживает темы через questions.json
    if task_module == 'test_part':
        questions_file = os.path.join(base_dir, 'data', 'questions.json')
        return os.path.exists(questions_file)

    # Специальная проверка для task24
    if task_module == 'task24':
        plans_file = os.path.join(base_dir, 'data', 'plans_data_with_blocks.json')
        return os.path.exists(plans_file)

    # Проверка для остальных модулей
    topics_file = os.path.join(base_dir, task_module, f"{task_module}_topics.json")
    return os.path.exists(topics_file)
