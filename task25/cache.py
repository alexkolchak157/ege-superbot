"""Простой кэш для данных task25."""

import time
from typing import Any, Optional, Dict

class SimpleCache:
    """Простой in-memory кэш с TTL."""
    
    def __init__(self, default_ttl: int = 3600):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl
    
    async def get(self, key: str) -> Optional[Any]:
        """Получить значение из кэша."""
        if key in self._cache:
            entry = self._cache[key]
            if entry['expires'] > time.time():
                return entry['value']
            else:
                # Удаляем устаревшую запись
                del self._cache[key]
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Сохранить значение в кэш."""
        expires = time.time() + (ttl or self.default_ttl)
        self._cache[key] = {
            'value': value,
            'expires': expires
        }
    
    async def delete(self, key: str) -> None:
        """Удалить значение из кэша."""
        if key in self._cache:
            del self._cache[key]
    
    async def clear(self) -> None:
        """Очистить весь кэш."""
        self._cache.clear()
    
    def cleanup(self) -> None:
        """Удалить устаревшие записи."""
        current_time = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry['expires'] <= current_time
        ]
        for key in expired_keys:
            del self._cache[key]

# Глобальный экземпляр кэша
cache = SimpleCache()