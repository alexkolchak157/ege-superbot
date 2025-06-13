"""Кэширование для улучшения производительности."""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import asyncio
import logging

logger = logging.getLogger(__name__)

class Task20Cache:
    """Кэш для данных задания 20."""
    
    def __init__(self, ttl_minutes: int = 30):
        self.ttl = timedelta(minutes=ttl_minutes)
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.locks: Dict[str, asyncio.Lock] = {}
    
    def _get_lock(self, key: str) -> asyncio.Lock:
        """Получить lock для ключа."""
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()
        return self.locks[key]
    
    def _is_expired(self, timestamp: datetime) -> bool:
        """Проверить, истёк ли срок кэша."""
        return datetime.now() - timestamp > self.ttl
    
    async def get(self, key: str) -> Optional[Any]:
        """Получить значение из кэша."""
        async with self._get_lock(key):
            if key in self.cache:
                entry = self.cache[key]
                if not self._is_expired(entry['timestamp']):
                    return entry['value']
                else:
                    del self.cache[key]
            return None
    
    async def set(self, key: str, value: Any) -> None:
        """Сохранить значение в кэше."""
        async with self._get_lock(key):
            self.cache[key] = {
                'value': value,
                'timestamp': datetime.now()
            }
    
    async def clear_expired(self) -> int:
        """Очистить устаревшие записи."""
        expired_keys = []
        for key, entry in self.cache.items():
            if self._is_expired(entry['timestamp']):
                expired_keys.append(key)
        
        for key in expired_keys:
            async with self._get_lock(key):
                if key in self.cache:
                    del self.cache[key]
        
        return len(expired_keys)

# Глобальный экземпляр кэша
cache = Task20Cache()