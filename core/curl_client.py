"""
HTTP-клиент для работы с Cloudflare Worker прокси через системный curl.

Проблема: Python HTTP-библиотеки (aiohttp, httpx, curl_cffi с impersonate)
не могут корректно подключиться к CF Workers — получают таймаут с 0 байтами.
При этом системный curl из командной строки работает нормально.

Причины:
- aiohttp/httpx: неподходящий TLS-фингерпринт (JA3/JA4)
- curl_cffi + impersonate: HTTP/2 ALPN negotiation, несовместимый с CF Workers

Решение: вызов системного curl через asyncio subprocess.
Гарантированно работает, т.к. использует тот же бинарник что и из консоли.

Используется для:
- Claude Vision API через CF Worker прокси (vision_service.py)
- Claude Text API через CF Worker прокси (ai_service.py)
"""

import json
import logging
import asyncio
import shutil
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Проверяем наличие curl в системе
CURL_PATH = shutil.which("curl")
AVAILABLE = CURL_PATH is not None

if not AVAILABLE:
    logger.warning(
        "curl не найден в системе — прокси через CF Worker работать не будет"
    )

# Уникальный разделитель для извлечения HTTP status code из вывода curl
_STATUS_SEP = "\n___HTTP_STATUS___"


async def post_json(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: int = 120,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    POST JSON через системный curl (subprocess).

    Тело запроса передаётся через stdin (--data-binary @-),
    что позволяет отправлять большие payload'ы (base64-изображения).

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
        - data (dict|None): Парсенный JSON (None если SSE или ошибка)
    """
    if not AVAILABLE:
        raise RuntimeError(
            "curl не найден. Установите curl для работы с CF Worker прокси."
        )

    cmd = [
        CURL_PATH,
        "-s", "-S",                          # Silent mode, но показывать ошибки
        "--connect-timeout", "30",            # Таймаут подключения
        "--max-time", str(timeout),           # Общий таймаут
        "-X", "POST",
        "--data-binary", "@-",                # Тело из stdin
        "-w", _STATUS_SEP + "%{http_code}",   # HTTP-код в конце вывода
    ]

    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])

    if proxy:
        cmd.extend(["-x", proxy])

    cmd.append(url)

    json_bytes = json.dumps(payload).encode("utf-8")

    logger.debug(
        f"curl POST {url} (payload {len(json_bytes)} bytes, timeout {timeout}s)"
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=json_bytes),
            timeout=timeout + 10,  # Запас поверх curl --max-time
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(
            f"curl subprocess timed out after {timeout + 10}s"
        )

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"curl error (exit {proc.returncode}): {err}")

    output = stdout.decode("utf-8", errors="replace")

    # Извлекаем HTTP status code из конца вывода (добавлен через -w)
    parts = output.rsplit(_STATUS_SEP, 1)
    body = parts[0]
    try:
        status = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        status = 0

    result = {"status": status, "text": body}

    try:
        result["data"] = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        result["data"] = None

    return result


def parse_sse_response(text: str) -> Dict[str, Any]:
    """
    Парсинг SSE-ответа Claude API из полного текста.

    curl буферизует весь streaming-ответ и возвращает целиком.
    Эта функция извлекает данные из SSE-событий и собирает
    финальный ответ в формате Claude API.

    Args:
        text: Полный текст SSE-ответа

    Returns:
        dict в формате Claude API response (content, model, usage)
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
