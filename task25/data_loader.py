"""Загрузчик данных для задания 25."""

import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def load_data_sync() -> Optional[Dict[str, Any]]:
    """Синхронная загрузка данных из JSON файла."""
    data_file = os.path.join(os.path.dirname(__file__), "task25_topics.json")

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            # Если это список тем, оборачиваем в словарь
            return {"topics": data}
        elif isinstance(data, dict) and "topics" in data:
            return data
        else:
            logger.error("Unexpected data format in task25_topics.json")
            return {"topics": []}
    except FileNotFoundError:
        logger.error(f"Data file not found: {data_file}")
        return {"topics": []}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        return {"topics": []}
    except Exception as e:
        logger.error(f"Failed to load topics data: {e}")
        return {"topics": []}


def get_data() -> Dict[str, Any]:
    """Получить данные для задания 25.

    Returns:
        Словарь с ключом 'topics', содержащий список тем.
    """
    return load_data_sync()
