"""Модуль кэширования для задания 25."""

import json
import logging
import os
import pickle
from datetime import datetime, timedelta
from typing import Any, Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)


class SimpleCache:
    """Простой файловый кэш для данных задания 25."""
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        Инициализация кэша.
        
        Args:
            cache_dir: Директория для хранения кэша
        """
        if cache_dir is None:
            # Используем директорию модуля по умолчанию
            cache_dir = os.path.join(os.path.dirname(__file__), '.cache')
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # Словарь для хранения данных в памяти
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"Cache initialized at: {self.cache_dir}")
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Получить значение из кэша.
        
        Args:
            key: Ключ для поиска
            
        Returns:
            Закэшированное значение или None
        """
        # Сначала проверяем память
        if key in self.memory_cache:
            entry = self.memory_cache[key]
            if self._is_valid(entry):
                logger.debug(f"Cache hit (memory): {key}")
                return entry['value']
            else:
                # Удаляем устаревшую запись
                del self.memory_cache[key]
        
        # Проверяем файловый кэш
        file_path = self._get_file_path(key)
        if file_path.exists():
            try:
                with open(file_path, 'rb') as f:
                    entry = pickle.load(f)
                
                if self._is_valid(entry):
                    # Загружаем в память для быстрого доступа
                    self.memory_cache[key] = entry
                    logger.debug(f"Cache hit (file): {key}")
                    return entry['value']
                else:
                    # Удаляем устаревший файл
                    file_path.unlink()
                    logger.debug(f"Cache expired: {key}")
            
            except Exception as e:
                logger.error(f"Error reading cache file {key}: {e}")
                # Удаляем повреждённый файл
                file_path.unlink()
        
        logger.debug(f"Cache miss: {key}")
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        Сохранить значение в кэш.
        
        Args:
            key: Ключ для сохранения
            value: Значение для сохранения
            ttl: Время жизни в секундах (по умолчанию 1 час)
        """
        if ttl is None:
            ttl = 3600  # 1 час по умолчанию
        
        entry = {
            'value': value,
            'created_at': datetime.now(),
            'ttl': ttl
        }
        
        # Сохраняем в память
        self.memory_cache[key] = entry
        
        # Сохраняем в файл
        file_path = self._get_file_path(key)
        try:
            with open(file_path, 'wb') as f:
                pickle.dump(entry, f)
            logger.debug(f"Cache set: {key} (ttl={ttl}s)")
        except Exception as e:
            logger.error(f"Error writing cache file {key}: {e}")
    
    async def delete(self, key: str):
        """
        Удалить значение из кэша.
        
        Args:
            key: Ключ для удаления
        """
        # Удаляем из памяти
        if key in self.memory_cache:
            del self.memory_cache[key]
        
        # Удаляем файл
        file_path = self._get_file_path(key)
        if file_path.exists():
            file_path.unlink()
            logger.debug(f"Cache deleted: {key}")
    
    async def clear(self):
        """Очистить весь кэш."""
        # Очищаем память
        self.memory_cache.clear()
        
        # Удаляем все файлы кэша
        for file_path in self.cache_dir.glob('*.cache'):
            file_path.unlink()
        
        logger.info("Cache cleared")
    
    def _get_file_path(self, key: str) -> Path:
        """Получить путь к файлу кэша."""
        # Безопасное имя файла
        safe_key = key.replace('/', '_').replace('\\', '_')
        return self.cache_dir / f"{safe_key}.cache"
    
    def _is_valid(self, entry: Dict[str, Any]) -> bool:
        """Проверить, действительна ли запись кэша."""
        created_at = entry.get('created_at')
        ttl = entry.get('ttl', 0)
        
        if not created_at:
            return False
        
        # Проверяем срок действия
        age = (datetime.now() - created_at).total_seconds()
        return age < ttl


class EvaluationCache(SimpleCache):
    """Специализированный кэш для результатов оценки."""
    
    def __init__(self):
        super().__init__(cache_dir=os.path.join(os.path.dirname(__file__), '.eval_cache'))
    
    async def get_evaluation(
        self, 
        user_id: int, 
        topic_id: str, 
        answer_hash: str
    ) -> Optional[Dict]:
        """
        Получить закэшированный результат оценки.
        
        Args:
            user_id: ID пользователя
            topic_id: ID темы
            answer_hash: Хэш ответа
            
        Returns:
            Результат оценки или None
        """
        key = f"eval_{user_id}_{topic_id}_{answer_hash}"
        return await self.get(key)
    
    async def set_evaluation(
        self, 
        user_id: int, 
        topic_id: str, 
        answer_hash: str,
        result: Dict,
        ttl: int = 86400  # 24 часа
    ):
        """
        Сохранить результат оценки в кэш.
        
        Args:
            user_id: ID пользователя
            topic_id: ID темы
            answer_hash: Хэш ответа
            result: Результат оценки
            ttl: Время жизни в секундах
        """
        key = f"eval_{user_id}_{topic_id}_{answer_hash}"
        await self.set(key, result, ttl)
    
    @staticmethod
    def hash_answer(answer: str) -> str:
        """
        Создать хэш ответа для использования в кэше.
        
        Args:
            answer: Текст ответа
            
        Returns:
            Хэш-строка
        """
        import hashlib
        # Нормализуем текст
        normalized = answer.strip().lower()
        # Создаём хэш
        return hashlib.md5(normalized.encode()).hexdigest()[:16]


# Глобальные экземпляры кэшей
cache = SimpleCache()
eval_cache = EvaluationCache()


# Утилиты для работы с кэшем
async def cached_topics_data():
    """Получить закэшированные данные тем."""
    data = await cache.get('task25_topics_data')
    if data:
        return data
    
    # Загружаем из файла
    data_file = os.path.join(os.path.dirname(__file__), "task25_topics.json")
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Кэшируем на 1 день
        await cache.set('task25_topics_data', data, ttl=86400)
        return data
    except Exception as e:
        logger.error(f"Failed to load topics data: {e}")
        return None


async def invalidate_topics_cache():
    """Инвалидировать кэш данных тем."""
    await cache.delete('task25_topics_data')
    logger.info("Topics cache invalidated")