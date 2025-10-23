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
        """Закрывает сессию при выходе из контекстного менеджера"""
        await self.cleanup()  # Вызываем cleanup для закрытия сессии
    
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
        temperature: Optional[float] = None,
        retry_on_error: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Получение ответа в формате JSON

        Автоматически добавляет инструкции для возврата JSON
        С улучшенной обработкой ошибок парсинга
        """
        json_instruction = "\n\nОтветь ТОЛЬКО валидным JSON без дополнительного текста, комментариев и пояснений."

        result = await self.get_completion(
            prompt + json_instruction,
            system_prompt=system_prompt,
            temperature=temperature or 0.1  # Низкая температура для JSON
        )

        if not result["success"]:
            return None

        try:
            text = result["text"].strip()

            # Улучшенная очистка текста
            # 1. Убираем markdown-теги
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            text = text.strip()

            # 2. Ищем JSON в тексте (если AI добавил текст до/после)
            # Находим первую { или [ и последнюю } или ]
            start_brace = text.find('{')
            start_bracket = text.find('[')

            # Определяем начало JSON
            if start_brace == -1 and start_bracket == -1:
                raise json.JSONDecodeError("No JSON object found", text, 0)

            if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
                start_pos = start_brace
                end_char = '}'
            else:
                start_pos = start_bracket
                end_char = ']'

            # Находим конец JSON
            end_pos = text.rfind(end_char)

            if end_pos != -1 and start_pos != -1:
                text = text[start_pos:end_pos + 1]

            # 3. Пытаемся распарсить
            parsed = json.loads(text)
            return parsed

        except json.JSONDecodeError as e:
            logger.error(f"Не удалось распарсить JSON: {e}")
            logger.warning(f"Проблемный текст (первые 500 символов): {result['text'][:500]}")

            # НОВОЕ: Повторная попытка с более строгим промптом
            if retry_on_error:
                logger.info("Попытка повторного запроса с усиленным промптом...")
                strict_instruction = (
                    "\n\nВНИМАНИЕ! Ответ ДОЛЖЕН быть ТОЛЬКО валидным JSON."
                    "\nНЕ добавляй НИКАКОГО текста до или после JSON."
                    "\nПРОВЕРЬ синтаксис: все запятые, скобки, кавычки должны быть на месте."
                )

                retry_result = await self.get_completion(
                    prompt + strict_instruction,
                    system_prompt=system_prompt,
                    temperature=0.05  # Ещё ниже температура
                )

                if retry_result["success"]:
                    # Пробуем снова распарсить
                    return await self.get_json_completion(
                        prompt="",  # Не добавляем промпт, используем уже полученный текст
                        system_prompt=None,
                        temperature=None,
                        retry_on_error=False  # Предотвращаем бесконечную рекурсию
                    ) if False else self._parse_json_response(retry_result["text"])

            return None

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Вспомогательная функция для парсинга JSON из текста"""
        try:
            text = text.strip()

            # Убираем markdown
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            text = text.strip()

            # Извлекаем JSON
            start_brace = text.find('{')
            start_bracket = text.find('[')

            if start_brace == -1 and start_bracket == -1:
                return None

            if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
                start_pos = start_brace
                end_char = '}'
            else:
                start_pos = start_bracket
                end_char = ']'

            end_pos = text.rfind(end_char)

            if end_pos != -1 and start_pos != -1:
                text = text[start_pos:end_pos + 1]

            return json.loads(text)
        except:
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