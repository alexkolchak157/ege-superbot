#!/usr/bin/env python3
"""
Диагностика подключения к Claude API.

Запуск на VDS:
    python test_claude_connection.py

Тестирует все доступные методы подключения:
1. Прямой запрос к api.anthropic.com (httpx/aiohttp)
2. Через CF Worker прокси (httpx/aiohttp)
3. Через CF Worker прокси (системный curl subprocess)

Использует переменные из .env файла.
"""

import os
import sys
import json
import time
import asyncio
import shutil
import subprocess

# Загружаем .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PROXY_URL = os.getenv("ANTHROPIC_PROXY_URL", "")
HTTP_PROXY = os.getenv("ANTHROPIC_HTTP_PROXY", "")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
TEST_PAYLOAD = {
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 50,
    "messages": [{"role": "user", "content": "Ответь одним словом: столица России?"}],
}
HEADERS = {
    "x-api-key": API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}


def print_result(name: str, success: bool, duration: float, detail: str):
    status = "OK" if success else "FAIL"
    print(f"\n{'='*60}")
    print(f"[{status}] {name}")
    print(f"  Время: {duration:.1f}s")
    print(f"  {detail}")
    print(f"{'='*60}")


# ============================================================
# Тест 1: Прямой запрос через aiohttp
# ============================================================
async def test_direct_aiohttp():
    name = "Прямой запрос (aiohttp -> api.anthropic.com)"
    try:
        import aiohttp
    except ImportError:
        print_result(name, False, 0, "aiohttp не установлен")
        return

    start = time.time()
    try:
        timeout = aiohttp.ClientTimeout(total=30, sock_connect=10)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                CLAUDE_API_URL,
                json=TEST_PAYLOAD,
                headers=HEADERS,
                timeout=timeout,
            ) as resp:
                body = await resp.text()
                duration = time.time() - start
                if resp.status == 200:
                    data = json.loads(body)
                    text = data["content"][0]["text"]
                    print_result(name, True, duration, f"Ответ: {text}")
                else:
                    print_result(name, False, duration,
                                 f"HTTP {resp.status}: {body[:200]}")
    except Exception as e:
        print_result(name, False, time.time() - start, f"Ошибка: {e}")


# ============================================================
# Тест 2: Через CF Worker прокси (aiohttp)
# ============================================================
async def test_proxy_aiohttp():
    name = "CF Worker прокси (aiohttp)"
    if not PROXY_URL:
        print_result(name, False, 0, "ANTHROPIC_PROXY_URL не задан — пропуск")
        return

    try:
        import aiohttp
    except ImportError:
        print_result(name, False, 0, "aiohttp не установлен")
        return

    url = PROXY_URL.rstrip("/") + "/v1/messages"
    start = time.time()
    try:
        timeout = aiohttp.ClientTimeout(total=30, sock_connect=10)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=TEST_PAYLOAD,
                headers=HEADERS,
                timeout=timeout,
                proxy=HTTP_PROXY or None,
            ) as resp:
                body = await resp.text()
                duration = time.time() - start
                if resp.status == 200:
                    data = json.loads(body)
                    text = data["content"][0]["text"]
                    print_result(name, True, duration, f"Ответ: {text}")
                else:
                    print_result(name, False, duration,
                                 f"HTTP {resp.status}: {body[:200]}")
    except Exception as e:
        print_result(name, False, time.time() - start, f"Ошибка: {e}")


# ============================================================
# Тест 3: Через CF Worker прокси (subprocess curl, без stream)
# ============================================================
async def test_proxy_curl_no_stream():
    name = "CF Worker прокси (subprocess curl, без stream)"
    if not PROXY_URL:
        print_result(name, False, 0, "ANTHROPIC_PROXY_URL не задан — пропуск")
        return

    curl_path = shutil.which("curl")
    if not curl_path:
        print_result(name, False, 0, "curl не найден в PATH")
        return

    url = PROXY_URL.rstrip("/") + "/v1/messages"
    cmd = [
        curl_path, "-s", "-S",
        "--connect-timeout", "10",
        "--max-time", "30",
        "-X", "POST",
        "--data-binary", "@-",
        "-w", "\n___STATUS___%{http_code}",
    ]
    for k, v in HEADERS.items():
        cmd.extend(["-H", f"{k}: {v}"])
    if HTTP_PROXY:
        cmd.extend(["-x", HTTP_PROXY])
    cmd.append(url)

    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=json.dumps(TEST_PAYLOAD).encode()),
            timeout=35,
        )
        duration = time.time() - start
        output = stdout.decode("utf-8", errors="replace")
        parts = output.rsplit("\n___STATUS___", 1)
        body = parts[0]
        status = int(parts[1]) if len(parts) > 1 else 0

        if status == 200:
            data = json.loads(body)
            text = data["content"][0]["text"]
            print_result(name, True, duration, f"Ответ: {text}")
        elif status == 0 and proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            print_result(name, False, duration, f"curl error: {err}")
        else:
            print_result(name, False, duration,
                         f"HTTP {status}: {body[:200]}")
    except Exception as e:
        print_result(name, False, time.time() - start, f"Ошибка: {e}")


# ============================================================
# Тест 4: Через CF Worker прокси (subprocess curl, stream)
# ============================================================
async def test_proxy_curl_stream():
    name = "CF Worker прокси (subprocess curl, stream=True)"
    if not PROXY_URL:
        print_result(name, False, 0, "ANTHROPIC_PROXY_URL не задан — пропуск")
        return

    curl_path = shutil.which("curl")
    if not curl_path:
        print_result(name, False, 0, "curl не найден в PATH")
        return

    url = PROXY_URL.rstrip("/") + "/v1/messages"
    payload = {**TEST_PAYLOAD, "stream": True}
    cmd = [
        curl_path, "-s", "-S",
        "--connect-timeout", "10",
        "--max-time", "60",
        "-X", "POST",
        "--data-binary", "@-",
        "-w", "\n___STATUS___%{http_code}",
    ]
    for k, v in HEADERS.items():
        cmd.extend(["-H", f"{k}: {v}"])
    if HTTP_PROXY:
        cmd.extend(["-x", HTTP_PROXY])
    cmd.append(url)

    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=json.dumps(payload).encode()),
            timeout=65,
        )
        duration = time.time() - start
        output = stdout.decode("utf-8", errors="replace")
        parts = output.rsplit("\n___STATUS___", 1)
        body = parts[0]
        status = int(parts[1]) if len(parts) > 1 else 0

        if status == 200:
            # Парсим SSE
            text_parts = []
            for line in body.split("\n"):
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    evt = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if evt.get("type") == "content_block_delta":
                    delta = evt.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text_parts.append(delta.get("text", ""))
            text = "".join(text_parts)
            print_result(name, True, duration, f"Ответ: {text}")
        elif status == 0 and proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            print_result(name, False, duration, f"curl error: {err}")
        else:
            print_result(name, False, duration,
                         f"HTTP {status}: {body[:300]}")
    except Exception as e:
        print_result(name, False, time.time() - start, f"Ошибка: {e}")


# ============================================================
# Тест 5: Системный curl из консоли (для сравнения)
# ============================================================
def test_system_curl():
    name = "Системный curl (синхронный, для сравнения)"
    if not PROXY_URL:
        print_result(name, False, 0, "ANTHROPIC_PROXY_URL не задан — пропуск")
        return

    curl_path = shutil.which("curl")
    if not curl_path:
        print_result(name, False, 0, "curl не найден в PATH")
        return

    url = PROXY_URL.rstrip("/") + "/v1/messages"
    cmd = [
        curl_path, "-s", "-S",
        "--connect-timeout", "10",
        "--max-time", "30",
        "-X", "POST",
        "-H", f"x-api-key: {API_KEY}",
        "-H", "anthropic-version: 2023-06-01",
        "-H", "content-type: application/json",
        "-d", json.dumps(TEST_PAYLOAD),
        "-w", "\n___STATUS___%{http_code}",
    ]
    if HTTP_PROXY:
        cmd.extend(["-x", HTTP_PROXY])
    cmd.append(url)

    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        duration = time.time() - start
        output = result.stdout
        parts = output.rsplit("\n___STATUS___", 1)
        body = parts[0]
        status = int(parts[1]) if len(parts) > 1 else 0

        if status == 200:
            data = json.loads(body)
            text = data["content"][0]["text"]
            print_result(name, True, duration, f"Ответ: {text}")
        elif status == 0 and result.returncode != 0:
            print_result(name, False, duration,
                         f"curl error (exit {result.returncode}): {result.stderr[:200]}")
        else:
            print_result(name, False, duration,
                         f"HTTP {status}: {body[:200]}")
    except Exception as e:
        print_result(name, False, time.time() - start, f"Ошибка: {e}")


# ============================================================
# Main
# ============================================================
async def main():
    print("=" * 60)
    print("  Диагностика подключения к Claude API")
    print("=" * 60)

    if not API_KEY:
        print("\nОШИБКА: ANTHROPIC_API_KEY не задан!")
        print("Установите переменную в .env или экспортируйте:")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    print(f"\n  API Key:    {API_KEY[:15]}...{API_KEY[-4:]}")
    print(f"  Proxy URL:  {PROXY_URL or '(не задан)'}")
    print(f"  HTTP Proxy: {HTTP_PROXY or '(не задан)'}")
    print(f"  curl:       {shutil.which('curl') or '(не найден)'}")

    # Тест 1: прямой запрос
    await test_direct_aiohttp()

    # Тест 2: CF Worker через aiohttp
    await test_proxy_aiohttp()

    # Тест 3: CF Worker через subprocess curl (без stream)
    await test_proxy_curl_no_stream()

    # Тест 4: CF Worker через subprocess curl (stream)
    await test_proxy_curl_stream()

    # Тест 5: системный curl (синхронный)
    test_system_curl()

    print("\n" + "=" * 60)
    print("  Диагностика завершена")
    print("=" * 60)
    print()
    print("Если работает ТОЛЬКО системный curl (тест 5),")
    print("а subprocess curl (тесты 3-4) — нет, сообщите об этом.")
    print()
    print("Для переключения на Yandex (фоллбек):")
    print("  В .env: AI_PROVIDER=yandex")
    print()


if __name__ == "__main__":
    asyncio.run(main())
