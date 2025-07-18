import os
import json
import logging
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class YandexGPTModel(Enum):
    """Доступные модели YandexGPT"""
    LITE = "yandexgpt-lite"  # Быстрая и дешевая
    PRO = "yandexgpt"  # Более качественная


@dataclass
class YandexGPTConfig:
    """Конфигурация для YandexGPT"""
    api_key: str
    folder_id: str
    model: YandexGPTModel = YandexGPTModel.LITE
    temperature: float = 0.3  # Для образовательных задач лучше низкая
    max_tokens: int = 2000
    retries: int = 3
    retry_delay: float = 2.0
    timeout: int = 60
    
    @classmethod
    def from_env(cls):
        """Создание конфигурации из переменных окружения"""
        api_key = os.getenv('YANDEX_GPT_API_KEY')
        folder_id = os.getenv('YANDEX_GPT_FOLDER_ID')
        
        if not api_key or not folder_id:
            raise ValueError(
                "Необходимо установить переменные окружения: "
                "YANDEX_GPT_API_KEY и YANDEX_GPT_FOLDER_ID"
            )
        retries = int(os.getenv('YANDEX_GPT_RETRIES', '3'))
        retry_delay = float(os.getenv('YANDEX_GPT_RETRY_DELAY', '2'))
        timeout = int(os.getenv('YANDEX_GPT_TIMEOUT', '60'))

        return cls(
            api_key=api_key,
            folder_id=folder_id,
            retries=retries,
            retry_delay=retry_delay,
            timeout=timeout,
        )


class YandexGPTService:
    """Сервис для работы с YandexGPT API"""
    
    BASE_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    
    def __init__(self, config: YandexGPTConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self):
        """Создает сессию если её нет"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
    
    async def _close_session(self):
        """Закрывает сессию если она открыта"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def __aenter__(self):
        """Для обратной совместимости с async with"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Для обратной совместимости с async with"""
        pass
    
    async def cleanup(self):
        """Очистка ресурсов"""
        await self._close_session()
        
    async def get_completion(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Получение ответа от YandexGPT
        
        Args:
            prompt: Основной запрос
            system_prompt: Системный промпт (роль)
            temperature: Температура генерации
            max_tokens: Максимальное количество токенов
            
        Returns:
            Словарь с ответом и метаданными
        """
        # Автоматически создаем сессию если её нет
        await self._ensure_session()
        
        # Формирование сообщений
        messages = []
        
        if system_prompt:
            messages.append({
                "role": "system",
                "text": system_prompt
            })
        
        messages.append({
            "role": "user",
            "text": prompt
        })
        
        # Подготовка запроса
        payload = {
            "modelUri": f"gpt://{self.config.folder_id}/{self.config.model.value}",
            "completionOptions": {
                "stream": False,
                "temperature": temperature or self.config.temperature,
                "maxTokens": str(max_tokens or self.config.max_tokens)
            },
            "messages": messages
        }
        
        headers = {
            "Authorization": f"Api-Key {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(self.config.retries):
            try:
                response = await self._session.post(
                    self.BASE_URL,
                    json=payload,
                    headers=headers,
                    timeout=self.config.timeout,
                )

                # Если ответ возвращает менеджер контекста, корректно выходим из него
                if hasattr(response, "__aenter__"):
                    async with response:
                        response_data = await response.json()
                else:
                    response_data = await response.json()

                if response.status != 200:
                    logger.error(f"YandexGPT API error: {response_data}")
                    if attempt == self.config.retries - 1:
                        return {
                            "success": False,
                            "error": response_data.get("message", "Unknown error"),
                            "status_code": response.status,
                        }
                    await asyncio.sleep(self.config.retry_delay)
                    continue

                # Извлекаем текст ответа
                alternatives = response_data.get("result", {}).get("alternatives", [])
                if alternatives:
                    text = alternatives[0].get("message", {}).get("text", "")
                else:
                    text = ""

                return {
                    "success": True,
                    "text": text,
                    "usage": response_data.get("result", {}).get("usage", {}),
                    "model_version": response_data.get("result", {}).get("modelVersion", ""),
                }

            except Exception as e:
                logger.error(f"Ошибка при запросе к YandexGPT: {e}")
                if attempt == self.config.retries - 1:
                    return {
                        "success": False,
                        "error": str(e),
                    }
                await asyncio.sleep(self.config.retry_delay)
    
    async def get_json_completion(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Получение ответа в формате JSON
        
        Автоматически добавляет инструкции для возврата JSON
        """
        json_instruction = "\n\nОтветь ТОЛЬКО валидным JSON без дополнительного текста."
        
        result = await self.get_completion(
            prompt + json_instruction,
            system_prompt=system_prompt,
            temperature=temperature or 0.1  # Низкая температура для JSON
        )
        
        if not result["success"]:
            return None
        
        try:
            # Пытаемся распарсить JSON
            text = result["text"].strip()
            # Убираем возможные markdown-теги
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Не удалось распарсить JSON: {e}")
            logger.debug(f"Полученный текст: {result['text']}")
            return None


# Глобальный экземпляр сервиса
_service_instance: Optional[YandexGPTService] = None


def get_ai_service() -> YandexGPTService:
    """Получение глобального экземпляра сервиса"""
    global _service_instance
    
    if _service_instance is None:
        config = YandexGPTConfig.from_env()
        _service_instance = YandexGPTService(config)
    
    return _service_instance