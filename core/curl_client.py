"""
HTTP-клиент на базе curl_cffi для работы с Cloudflare-защищёнными эндпоинтами.

Проблема: стандартные Python HTTP-библиотеки (aiohttp, httpx) блокируются
Cloudflare на уровне TLS-фингерпринтинга (JA3/JA4). Cloudflare определяет
автоматизированных клиентов по паттерну TLS-рукопожатия и блокирует их,
возвращая challenge или просто сбрасывая соединение (таймаут без ответа).

Решение: curl_cffi использует libcurl, который создаёт TLS-фингерпринт,
идентичный реальному браузеру. Cloudflare распознаёт его как легитимный трафик.

Используется для:
- Claude Vision API через CF Worker прокси (vision_service.py)
- Claude Text API через CF Worker прокси (ai_service.py)
"""

import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    from curl_cffi.requests import AsyncSession
    AVAILABLE = True
except ImportError:
    AsyncSession = None
    AVAILABLE = False
    logger.info(
        "curl_cffi не установлен — CF Worker прокси может не работать. "
        "Установите: pip install curl_cffi"
    )

# Имперсонация Chrome 120 — современный и распространённый фингерпринт
DEFAULT_IMPERSONATE = "chrome120"


async def post_json(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: int = 120,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    POST-запрос с JSON-телом через curl_cffi.

    Args:
        url: URL запроса
        headers: HTTP-заголовки
        payload: JSON-тело запроса
        timeout: Таймаут в секундах
        proxy: HTTP/HTTPS прокси (опционально)

    Returns:
        dict с полями:
        - status (int): HTTP-код ответа
        - text (str): Тело ответа как текст
        - data (dict|None): Парсенный JSON (None если не удалось распарсить)
    """
    if not AVAILABLE:
        raise ImportError(
            "curl_cffi необходим для работы с CF Worker прокси. "
            "Установите: pip install curl_cffi"
        )

    kwargs = {
        "url": url,
        "headers": headers,
        "json": payload,
        "timeout": timeout,
        "impersonate": DEFAULT_IMPERSONATE,
    }
    if proxy:
        kwargs["proxy"] = proxy

    async with AsyncSession() as session:
        response = await session.post(**kwargs)

        result = {
            "status": response.status_code,
            "text": response.text,
        }

        try:
            result["data"] = response.json()
        except (json.JSONDecodeError, ValueError):
            result["data"] = None

        return result


def parse_sse_response(text: str) -> Dict[str, Any]:
    """
    Парсинг SSE-ответа Claude API из полного текста ответа.

    Когда curl_cffi получает streaming-ответ, он буферизует его целиком.
    Эта функция извлекает данные из SSE-событий и собирает финальный ответ
    в формате, совместимом с не-streaming ответом Claude API.

    Args:
        text: Полный текст SSE-ответа

    Returns:
        dict в формате Claude API response
    """
    text_parts = []
    input_tokens = 0
    output_tokens = 0
    model = ""

    for line in text.split('\n'):
        line = line.strip()
        if not line.startswith('data: '):
            continue
        data_str = line[6:]
        if data_str == '[DONE]':
            break
        try:
            event = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        event_type = event.get('type', '')

        if event_type == 'message_start':
            msg = event.get('message', {})
            model = msg.get('model', '')
            usage = msg.get('usage', {})
            input_tokens = usage.get('input_tokens', 0)

        elif event_type == 'content_block_delta':
            delta = event.get('delta', {})
            if delta.get('type') == 'text_delta':
                text_parts.append(delta.get('text', ''))

        elif event_type == 'message_delta':
            usage = event.get('usage', {})
            output_tokens = usage.get('output_tokens', 0)

    return {
        "content": [{"type": "text", "text": "".join(text_parts)}],
        "model": model,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }
