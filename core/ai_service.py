"""
core/ai_service.py
Мультипровайдерный AI-сервис для проверки заданий ЕГЭ.

Поддерживаемые провайдеры:
- Claude (Anthropic) — рекомендуемый, лучшее качество рассуждений и JSON-генерации
- YandexGPT — legacy-поддержка

Выбор провайдера: переменная окружения AI_PROVIDER (claude / yandex)
"""

import os
import json
import logging
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from enum import Enum

from core import curl_client

logger = logging.getLogger(__name__)


# ==================== Общие типы ====================

class AIProvider(Enum):
    """Доступные AI-провайдеры"""
    YANDEX = "yandex"
    CLAUDE = "claude"


class AIModel(Enum):
    """Унифицированный уровень модели"""
    LITE = "lite"   # Быстрая, но умная (Claude Sonnet / YandexGPT Lite)
    PRO = "pro"     # Максимальное качество рассуждений (Claude Opus / YandexGPT Pro)


# Маппинг на конкретные model ID
CLAUDE_MODELS = {
    AIModel.LITE: "claude-sonnet-4-5-20250929",
    AIModel.PRO: "claude-opus-4-20250514",
}

YANDEX_MODELS = {
    AIModel.LITE: "yandexgpt-lite",
    AIModel.PRO: "yandexgpt",
}


def _get_provider() -> AIProvider:
    """Определение текущего AI-провайдера из переменной окружения"""
    provider_str = os.getenv('AI_PROVIDER', 'claude').lower()
    try:
        return AIProvider(provider_str)
    except ValueError:
        logger.warning(f"Неизвестный AI_PROVIDER={provider_str}, используем claude")
        return AIProvider.CLAUDE


# ==================== Провайдер-агностичная конфигурация ====================

@dataclass
class AIServiceConfig:
    """Конфигурация AI-сервиса (работает для любого провайдера)"""
    api_key: str
    model: AIModel = AIModel.PRO
    temperature: float = 0.3
    max_tokens: int = 2000
    retries: int = 3
    retry_delay: float = 2.0
    timeout: int = 60
    # YandexGPT-specific
    folder_id: Optional[str] = None
    # Прокси для Claude API (обход гео-блокировки)
    proxy_url: Optional[str] = None        # Reverse proxy base URL
    http_proxy: Optional[str] = None       # Standard HTTP proxy

    @classmethod
    def from_env(cls) -> 'AIServiceConfig':
        """Создание конфигурации из переменных окружения"""
        provider = _get_provider()

        if provider == AIProvider.YANDEX:
            api_key = os.getenv('YANDEX_GPT_API_KEY')
            folder_id = os.getenv('YANDEX_GPT_FOLDER_ID')
            if not api_key or not folder_id:
                raise ValueError(
                    "Необходимо установить переменные окружения: "
                    "YANDEX_GPT_API_KEY и YANDEX_GPT_FOLDER_ID"
                )
            return cls(
                api_key=api_key,
                folder_id=folder_id,
                retries=int(os.getenv('YANDEX_GPT_RETRIES', '3')),
                retry_delay=float(os.getenv('YANDEX_GPT_RETRY_DELAY', '2')),
                timeout=int(os.getenv('YANDEX_GPT_TIMEOUT', '60')),
            )
        else:  # CLAUDE
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError(
                    "Необходимо установить переменную окружения ANTHROPIC_API_KEY"
                )
            return cls(
                api_key=api_key,
                retries=int(os.getenv('CLAUDE_RETRIES', '3')),
                retry_delay=float(os.getenv('CLAUDE_RETRY_DELAY', '2')),
                timeout=int(os.getenv('CLAUDE_TIMEOUT', '120')),
                proxy_url=os.getenv('ANTHROPIC_PROXY_URL'),
                http_proxy=os.getenv('ANTHROPIC_HTTP_PROXY'),
            )


# ==================== Claude Service ====================

class ClaudeService:
    """Сервис для работы с Claude API (Anthropic)"""

    def __init__(self, config: AIServiceConfig):
        self.config = config
        self._client = None

    def _ensure_client(self):
        """Ленивая инициализация клиента Anthropic"""
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                import sys
                logger.error(
                    f"anthropic import failed: {e}. "
                    f"Python: {sys.executable} (v{sys.version.split()[0]}), "
                    f"path: {sys.path[:3]}"
                )
                raise ImportError(
                    f"Для использования Claude установите пакет: pip install anthropic "
                    f"(Python: {sys.executable}, ошибка: {e})"
                )
            kwargs = {
                "api_key": self.config.api_key,
                "timeout": self.config.timeout,
            }
            if self.config.proxy_url:
                kwargs["base_url"] = self.config.proxy_url
                logger.info(f"Claude API using reverse proxy: {self.config.proxy_url}")
            if self.config.http_proxy:
                import httpx
                kwargs["http_client"] = httpx.AsyncClient(proxy=self.config.http_proxy)
                logger.info(f"Claude API using HTTP proxy: {self.config.http_proxy}")
            self._client = anthropic.AsyncAnthropic(**kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    async def cleanup(self):
        """Очистка ресурсов"""
        if self._client is not None:
            await self._client.close()
            self._client = None

    @property
    def _use_curl(self) -> bool:
        """Нужен ли curl_cffi для обхода TLS-фингерпринтинга CF"""
        return (
            bool(self.config.proxy_url or self.config.http_proxy)
            and curl_client.AVAILABLE
        )

    async def _raw_completion_via_curl(
        self,
        model_id: str,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        max_tokens: int,
    ) -> Dict[str, Any]:
        """
        Прямой HTTP-запрос к Claude API через curl_cffi (минуя SDK).

        Используется когда запрос идёт через CF Worker прокси —
        httpx из SDK блокируется TLS-фингерпринтингом Cloudflare.
        """
        api_url = self.config.proxy_url or "https://api.anthropic.com"
        if '/v1/messages' not in api_url:
            api_url = api_url.rstrip('/') + '/v1/messages'

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,  # Streaming для CF Worker (не даём таймаутнуть)
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if system_prompt:
            payload["system"] = system_prompt

        result = await curl_client.post_json(
            url=api_url,
            headers=headers,
            payload=payload,
            timeout=self.config.timeout,
            proxy=self.config.http_proxy,
        )

        if result["status"] != 200:
            error_text = result["text"][:500]
            raise Exception(
                f"Claude API error {result['status']}: {error_text}"
            )

        response_data = curl_client.parse_sse_response(result["text"])
        return response_data

    async def get_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Получение ответа от Claude API

        Returns:
            Словарь с полями: success, text, usage, model_version
            (тот же формат, что и YandexGPTService)
        """
        model_id = CLAUDE_MODELS.get(self.config.model, CLAUDE_MODELS[AIModel.PRO])
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens or self.config.max_tokens

        for attempt in range(self.config.retries):
            try:
                if self._use_curl:
                    # curl_cffi: обход TLS-фингерпринтинга CF Worker
                    response_data = await self._raw_completion_via_curl(
                        model_id=model_id,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        temperature=temp,
                        max_tokens=tokens,
                    )
                    text_content = ""
                    for block in response_data.get("content", []):
                        if block.get("type") == "text":
                            text_content += block.get("text", "")

                    usage = response_data.get("usage", {})
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)

                    return {
                        "success": True,
                        "text": text_content,
                        "usage": {
                            "inputTextTokens": str(input_tokens),
                            "completionTokens": str(output_tokens),
                            "totalTokens": str(input_tokens + output_tokens),
                        },
                        "model_version": response_data.get("model", model_id),
                    }
                else:
                    # Anthropic SDK: прямое подключение к API
                    self._ensure_client()

                    kwargs = {
                        "model": model_id,
                        "max_tokens": tokens,
                        "messages": [{"role": "user", "content": prompt}],
                    }
                    if temp is not None:
                        kwargs["temperature"] = temp
                    if system_prompt:
                        kwargs["system"] = system_prompt

                    # Streaming через прокси (CF Workers таймаутят на долгих)
                    if self.config.proxy_url or self.config.http_proxy:
                        async with self._client.messages.stream(**kwargs) as stream:
                            response = await stream.get_final_message()
                    else:
                        response = await self._client.messages.create(**kwargs)

                    text = response.content[0].text if response.content else ""

                    return {
                        "success": True,
                        "text": text,
                        "usage": {
                            "inputTextTokens": str(response.usage.input_tokens),
                            "completionTokens": str(response.usage.output_tokens),
                            "totalTokens": str(
                                response.usage.input_tokens + response.usage.output_tokens
                            ),
                        },
                        "model_version": response.model,
                    }

            except Exception as e:
                logger.error(f"Ошибка при запросе к Claude API (попытка {attempt + 1}): {e}")
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
        Получение ответа в формате JSON.
        Claude значительно стабильнее генерирует JSON, чем YandexGPT.
        """
        json_instruction = (
            "\n\nОтветь ТОЛЬКО валидным JSON без дополнительного текста, "
            "комментариев и пояснений."
        )

        result = await self.get_completion(
            prompt + json_instruction,
            system_prompt=system_prompt,
            temperature=temperature if temperature is not None else 0.1,
        )

        if not result["success"]:
            return None

        parsed = self._parse_json_response(result["text"])
        if parsed is not None:
            return parsed

        # Если первая попытка не удалась — повторяем с более строгим промптом
        if retry_on_error:
            logger.info("JSON-парсинг не удался, повторяем запрос с усиленным промптом...")
            strict_instruction = (
                "\n\nВНИМАНИЕ! Ответ ДОЛЖЕН быть ТОЛЬКО валидным JSON."
                "\nНЕ добавляй НИКАКОГО текста до или после JSON."
                "\nПРОВЕРЬ синтаксис: все запятые, скобки, кавычки должны быть на месте."
            )
            retry_result = await self.get_completion(
                prompt + strict_instruction,
                system_prompt=system_prompt,
                temperature=0.05,
            )
            if retry_result["success"]:
                return self._parse_json_response(retry_result["text"])

        return None

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Парсинг JSON из текста ответа (с очисткой markdown и т.п.)"""
        try:
            text = text.strip()

            # Убираем markdown-обёртки
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            # Ищем JSON-объект или массив в тексте
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
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Не удалось распарсить JSON: {e}")
            logger.warning(f"Проблемный текст (первые 500 символов): {text[:500]}")
            return None


# ==================== YandexGPT Service (legacy) ====================

# Backward-compatible aliases
class YandexGPTModel(Enum):
    """Доступные модели YandexGPT"""
    LITE = "yandexgpt-lite"
    PRO = "yandexgpt"


@dataclass
class YandexGPTConfig:
    """Конфигурация для YandexGPT"""
    api_key: str
    folder_id: str
    model: YandexGPTModel = YandexGPTModel.LITE
    temperature: float = 0.3
    max_tokens: int = 2000
    retries: int = 3
    retry_delay: float = 2.0
    timeout: int = 60
    finetuned_model_uri: Optional[str] = None  # URI дообученной модели (ds://...)

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
        finetuned_uri = os.getenv('YANDEX_GPT_FINETUNED_MODEL_URI')

        return cls(
            api_key=api_key,
            folder_id=folder_id,
            retries=retries,
            retry_delay=retry_delay,
            timeout=timeout,
            finetuned_model_uri=finetuned_uri,
        )


class YandexGPTService:
    """Сервис для работы с YandexGPT API (legacy)"""

    BASE_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    def __init__(self, config: YandexGPTConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def _close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    async def cleanup(self):
        await self._close_session()
    def _get_model_uri(self, use_finetuned: bool = False) -> str:
        """
        Возвращает URI модели для запроса.

        Args:
            use_finetuned: Использовать дообученную модель, если доступна

        Returns:
            URI модели (gpt://... или ds://...)
        """
        if use_finetuned and self.config.finetuned_model_uri:
            return self.config.finetuned_model_uri
        return f"gpt://{self.config.folder_id}/{self.config.model.value}"

    async def get_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        use_finetuned: bool = False
    ) -> Dict[str, Any]:
        """
        Получение ответа от YandexGPT

        Args:
            prompt: Основной запрос
            system_prompt: Системный промпт (роль)
            temperature: Температура генерации
            max_tokens: Максимальное количество токенов
            use_finetuned: Использовать дообученную модель (если настроена)

        Returns:
            Словарь с ответом и метаданными
        """
        await self._ensure_session()

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

        model_uri = self._get_model_uri(use_finetuned=use_finetuned)

        payload = {
            "modelUri": model_uri,
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

                alternatives = response_data.get("result", {}).get("alternatives", [])
                text = alternatives[0].get("message", {}).get("text", "") if alternatives else ""

                return {
                    "success": True,
                    "text": text,
                    "usage": response_data.get("result", {}).get("usage", {}),
                    "model_version": response_data.get("result", {}).get("modelVersion", ""),
                }

            except Exception as e:
                logger.error(f"Ошибка при запросе к YandexGPT: {e}")
                if attempt == self.config.retries - 1:
                    return {"success": False, "error": str(e)}
                await asyncio.sleep(self.config.retry_delay)

    async def get_json_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        retry_on_error: bool = True
    ) -> Optional[Dict[str, Any]]:
        json_instruction = (
            "\n\nОтветь ТОЛЬКО валидным JSON без дополнительного текста, "
            "комментариев и пояснений."
        )

        result = await self.get_completion(
            prompt + json_instruction,
            system_prompt=system_prompt,
            temperature=temperature or 0.1,
        )

        if not result["success"]:
            return None

        try:
            text = result["text"].strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            start_brace = text.find('{')
            start_bracket = text.find('[')

            if start_brace == -1 and start_bracket == -1:
                raise json.JSONDecodeError("No JSON object found", text, 0)

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

        except json.JSONDecodeError as e:
            logger.error(f"Не удалось распарсить JSON: {e}")
            logger.warning(f"Проблемный текст (первые 500 символов): {result['text'][:500]}")

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
                    temperature=0.05,
                )
                if retry_result["success"]:
                    return self._parse_json_response(retry_result["text"])

            return None

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

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
        except Exception:
            return None


# ==================== Фабрика сервисов ====================

def create_ai_service(config: AIServiceConfig) -> Union[ClaudeService, YandexGPTService]:
    """
    Создаёт экземпляр AI-сервиса на основе текущего провайдера.

    Args:
        config: Провайдер-агностичная конфигурация

    Returns:
        ClaudeService или YandexGPTService
    """
    provider = _get_provider()

    if provider == AIProvider.YANDEX:
        yandex_model = (
            YandexGPTModel.PRO if config.model == AIModel.PRO else YandexGPTModel.LITE
        )
        yandex_config = YandexGPTConfig(
            api_key=config.api_key,
            folder_id=config.folder_id or '',
            model=yandex_model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            retries=config.retries,
            retry_delay=config.retry_delay,
            timeout=config.timeout,
        )
        return YandexGPTService(yandex_config)
    else:
        return ClaudeService(config)


# ==================== Глобальный экземпляр ====================

_service_instance = None


def get_ai_service() -> Union[ClaudeService, YandexGPTService]:
    """Получение глобального экземпляра AI-сервиса"""
    global _service_instance

    if _service_instance is None:
        config = AIServiceConfig.from_env()
        _service_instance = create_ai_service(config)

    return _service_instance
