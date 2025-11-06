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
        task_module: Название модуля ('task19', 'task20', 'task24', 'task25')

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
        task_module: Название модуля ('task19', 'task20', 'task24', 'task25')

    Returns:
        True если модуль имеет файл с темами
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    # Специальная проверка для task24
    if task_module == 'task24':
        plans_file = os.path.join(base_dir, 'data', 'plans_data_with_blocks.json')
        return os.path.exists(plans_file)

    # Проверка для остальных модулей
    topics_file = os.path.join(base_dir, task_module, f"{task_module}_topics.json")
    return os.path.exists(topics_file)
