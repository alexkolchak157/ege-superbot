"""
Vision service для распознавания текста с изображений.

Поддерживает два режима OCR:
1. Claude Vision API (приоритетный) — мультимодальная LLM, отлично
   читает рукописный текст напрямую с изображения
2. Yandex Vision API (фоллбек) — традиционный OCR с LLM-коррекцией
   через YandexGPT

Режим выбирается автоматически: если задан ANTHROPIC_API_KEY —
используется Claude Vision, иначе — Yandex Vision.
"""

import os
import json
import logging
import base64
import asyncio
import aiohttp
import html
from typing import Dict, Any, Optional, List
from telegram import PhotoSize, Bot
from dataclasses import dataclass

from core.image_preprocessor import preprocess_for_ocr, preprocess_for_ocr_enhanced
from core import curl_client

logger = logging.getLogger(__name__)

# Порог уверенности для применения LLM-коррекции (Yandex Vision фоллбек)
OCR_LLM_CORRECTION_THRESHOLD = 0.97
# Порог уверенности для повторной попытки с усиленной обработкой
OCR_ENHANCED_RETRY_THRESHOLD = 0.55

# Claude Vision API
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
CLAUDE_MAX_TOKENS = 4096


@dataclass
class VisionConfig:
    """Конфигурация для Vision сервисов"""
    api_key: str
    folder_id: str
    timeout: int = 30
    retries: int = 3
    retry_delay: float = 2.0
    anthropic_api_key: Optional[str] = None
    anthropic_proxy_url: Optional[str] = None    # Reverse proxy base URL
    anthropic_http_proxy: Optional[str] = None   # Standard HTTP proxy
    claude_vision_timeout: int = 120             # Отдельный таймаут для Claude Vision

    @classmethod
    def from_env(cls):
        """Создание конфигурации из переменных окружения"""
        # Yandex Vision / YandexGPT
        api_key = os.getenv('YANDEX_GPT_API_KEY')
        folder_id = os.getenv('YANDEX_GPT_FOLDER_ID')

        # Claude Vision (приоритетный OCR)
        anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
        anthropic_proxy_url = os.getenv('ANTHROPIC_PROXY_URL')
        anthropic_http_proxy = os.getenv('ANTHROPIC_HTTP_PROXY')

        if not api_key or not folder_id:
            if not anthropic_api_key:
                logger.warning(
                    "No Vision API credentials found. "
                    "OCR functionality will be disabled. "
                    "Set ANTHROPIC_API_KEY for Claude Vision or "
                    "YANDEX_GPT_API_KEY and YANDEX_GPT_FOLDER_ID for Yandex Vision."
                )
                return None
            # Если есть только Anthropic — создаём конфиг с заглушками для Yandex
            api_key = api_key or ""
            folder_id = folder_id or ""

        timeout = int(os.getenv('YANDEX_VISION_TIMEOUT', '30'))
        retries = int(os.getenv('YANDEX_VISION_RETRIES', '3'))
        retry_delay = float(os.getenv('YANDEX_VISION_RETRY_DELAY', '2.0'))
        claude_vision_timeout = int(os.getenv('CLAUDE_VISION_TIMEOUT', '120'))

        return cls(
            api_key=api_key,
            folder_id=folder_id,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
            anthropic_api_key=anthropic_api_key,
            anthropic_proxy_url=anthropic_proxy_url,
            anthropic_http_proxy=anthropic_http_proxy,
            claude_vision_timeout=claude_vision_timeout,
        )


class VisionService:
    """
    Сервис для распознавания текста с изображений.

    Приоритет: Claude Vision API > Yandex Vision API + YandexGPT коррекция.
    """

    VISION_API_URL = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"

    def __init__(self, config: Optional[VisionConfig] = None):
        """
        Инициализация сервиса.

        Args:
            config: Конфигурация API. Если None, попытается загрузить из env
        """
        if config is None:
            config = VisionConfig.from_env()

        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None

        if self.config is None:
            logger.warning("VisionService initialized without credentials - OCR disabled")
        elif self.config.anthropic_api_key:
            key = self.config.anthropic_api_key
            logger.info(
                f"VisionService initialized with Claude Vision API (primary), "
                f"key: {key[:10]}...{key[-4:]} (len={len(key)})"
            )
        else:
            logger.info("VisionService initialized with Yandex Vision API (fallback)")

    @property
    def is_available(self) -> bool:
        """Проверка доступности OCR"""
        return self.config is not None

    @property
    def _has_claude(self) -> bool:
        """Проверка доступности Claude Vision"""
        return self.config is not None and bool(self.config.anthropic_api_key)

    @property
    def _has_yandex(self) -> bool:
        """Проверка доступности Yandex Vision"""
        return (self.config is not None
                and bool(self.config.api_key)
                and bool(self.config.folder_id))

    async def _ensure_session(self):
        """Создает сессию если её нет"""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(force_close=True)
            self._session = aiohttp.ClientSession(connector=connector)

    async def _close_session(self):
        """Закрывает сессию если она открыта"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def cleanup(self):
        """Очистка ресурсов"""
        await self._close_session()

    async def process_telegram_photo(
        self,
        photo: PhotoSize,
        bot: Bot,
        task_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Обработка фотографии от Telegram.

        Стратегия:
        1. Если доступен Claude Vision — отправляем изображение напрямую
           в мультимодальную LLM (лучшее качество для рукописного текста)
        2. Иначе — Yandex Vision OCR + LLM-коррекция через YandexGPT

        Args:
            photo: Объект фотографии от Telegram
            bot: Экземпляр бота для загрузки фото
            task_context: Предметный контекст для улучшения коррекции

        Returns:
            Словарь с результатом обработки
        """
        if not self.is_available:
            return {
                'success': False,
                'error': 'OCR сервис недоступен. Пожалуйста, введите текст вручную.',
                'text': '',
                'confidence': 0.0
            }

        try:
            # Скачиваем фото
            logger.info(f"Downloading photo: {photo.file_id}")
            file = await bot.get_file(photo.file_id)
            photo_bytes = bytes(await file.download_as_bytearray())

            # === Путь 1: Claude Vision (приоритетный) ===
            if self._has_claude:
                logger.info("Using Claude Vision API for handwriting recognition")
                result = await self._recognize_with_claude(photo_bytes, task_context)

                if result['success']:
                    return result

                # Claude не смог — пробуем Yandex как фоллбек
                logger.warning(
                    f"Claude Vision failed: {result.get('error')}, "
                    "falling back to Yandex Vision"
                )
                if not self._has_yandex:
                    return result

            # === Путь 2: Yandex Vision OCR + LLM-коррекция (фоллбек) ===
            return await self._process_with_yandex(photo_bytes, task_context)

        except Exception as e:
            logger.error(f"Error processing photo: {e}", exc_info=True)
            return {
                'success': False,
                'error': f'Ошибка обработки фото: {str(e)}',
                'text': '',
                'confidence': 0.0
            }

    async def _process_with_yandex(
        self,
        photo_bytes: bytes,
        task_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """Обработка через Yandex Vision OCR + LLM-коррекция."""
        # Шаг 1: Предобработка изображения
        preprocessed_bytes = preprocess_for_ocr(photo_bytes)
        logger.info("Image preprocessed for Yandex OCR")

        # Шаг 2: Распознаём текст
        result = await self._recognize_text(preprocessed_bytes)

        if not result['success']:
            return result

        # Шаг 3: Низкая уверенность — повтор с усиленной обработкой
        if result['confidence'] < OCR_ENHANCED_RETRY_THRESHOLD and result['text']:
            logger.info(
                f"Low confidence ({result['confidence']:.2f}), "
                "retrying with enhanced preprocessing"
            )
            enhanced_bytes = preprocess_for_ocr_enhanced(photo_bytes)
            enhanced_result = await self._recognize_text(enhanced_bytes)

            if (enhanced_result['success'] and
                    enhanced_result['confidence'] > result['confidence']):
                logger.info(
                    f"Enhanced result better: {enhanced_result['confidence']:.2f} "
                    f"vs {result['confidence']:.2f}"
                )
                result = enhanced_result

        # Шаг 4: LLM-коррекция
        if result['success'] and result['confidence'] < OCR_LLM_CORRECTION_THRESHOLD:
            corrected_text = await self._correct_ocr_with_llm(result['text'], task_context)
            if corrected_text:
                result['text'] = corrected_text
                result['corrected'] = True
                logger.info("OCR text corrected by LLM")
            else:
                result['corrected'] = False
        else:
            result['corrected'] = False

        return result

    # ================================================================
    # Claude Vision API — распознавание рукописного текста напрямую
    # ================================================================

    async def _recognize_with_claude(
        self,
        image_bytes: bytes,
        task_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Распознавание рукописного текста через Claude Vision API.

        Отправляет изображение напрямую в мультимодальную LLM —
        Claude видит картинку и читает почерк значительно лучше
        традиционного OCR.

        Args:
            image_bytes: Исходные байты изображения (без предобработки)
            task_context: Предметный контекст

        Returns:
            Результат распознавания
        """
        await self._ensure_session()

        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Определяем MIME-тип по сигнатуре файла
        media_type = "image/jpeg"
        if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            media_type = "image/png"
        elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
            media_type = "image/webp"

        # Формируем промпт с контекстом
        context_hint = ""
        if task_context:
            context_hint = (
                f"\n\nКонтекст: {task_context}. "
                "Используй этот контекст для правильной интерпретации терминов."
            )

        user_prompt = (
            "На этой фотографии — рукописный ответ ученика на задание ЕГЭ по обществознанию. "
            "Внимательно прочитай весь рукописный текст на изображении и перепиши его "
            "максимально точно, сохраняя:\n"
            "- оригинальную структуру (абзацы, нумерацию, пункты)\n"
            "- авторскую пунктуацию и орфографию\n"
            "- все сокращения и пометки\n\n"
            "ВАЖНО:\n"
            "- НЕ исправляй грамматические ошибки ученика — перепиши как есть\n"
            "- НЕ добавляй от себя текст, которого нет на фото\n"
            "- НЕ пропускай слова или предложения\n"
            "- Если слово трудно разобрать, выбери наиболее вероятный вариант "
            "по контексту предложения\n\n"
            "Верни ТОЛЬКО распознанный текст, без комментариев и пояснений."
            f"{context_hint}"
        )

        payload = {
            "model": CLAUDE_MODEL,
            "max_tokens": CLAUDE_MAX_TOKENS,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_base64,
                            }
                        },
                        {
                            "type": "text",
                            "text": user_prompt
                        }
                    ]
                }
            ]
        }

        headers = {
            "x-api-key": self.config.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Если настроен прокси — используем его как base URL
        api_url = self.config.anthropic_proxy_url or CLAUDE_API_URL
        if self.config.anthropic_proxy_url:
            # Прокси-URL может быть как полным, так и только base URL
            if '/v1/messages' not in api_url:
                api_url = api_url.rstrip('/') + '/v1/messages'

        # HTTP-прокси для aiohttp
        http_proxy = self.config.anthropic_http_proxy

        # Через прокси используем streaming (не даём CF Worker таймаутнуть)
        use_proxy = bool(
            self.config.anthropic_proxy_url or self.config.anthropic_http_proxy
        )
        use_streaming = use_proxy
        if use_streaming:
            payload["stream"] = True

        # curl_cffi для CF Worker прокси (обход TLS-фингерпринтинга Cloudflare)
        use_curl = use_proxy and curl_client.AVAILABLE

        logger.info(
            f"Claude Vision API request to {api_url} "
            f"(stream={use_streaming}, curl={use_curl})"
        )

        for attempt in range(self.config.retries):
            try:
                if use_curl:
                    # curl_cffi: TLS-фингерпринт как у браузера
                    result = await curl_client.post_json(
                        url=api_url,
                        headers=headers,
                        payload=payload,
                        timeout=self.config.claude_vision_timeout,
                        proxy=http_proxy,
                    )
                    status = result["status"]
                    if status != 200:
                        error_text = result["text"]
                        key = self.config.anthropic_api_key or ""
                        logger.error(
                            f"Claude Vision API error: {status} - "
                            f"{error_text[:500]}. "
                            f"Key prefix: {key[:10]}..., model: {CLAUDE_MODEL}"
                        )
                        if status in (401, 403):
                            return {
                                'success': False,
                                'error': f'Ошибка авторизации Claude Vision API ({status})',
                                'text': '',
                                'confidence': 0.0,
                            }
                        if status >= 500 or status == 429:
                            if attempt < self.config.retries - 1:
                                await asyncio.sleep(
                                    self.config.retry_delay * (attempt + 1)
                                )
                                continue
                        return {
                            'success': False,
                            'error': f'Ошибка Claude Vision API: {status}',
                            'text': '',
                            'confidence': 0.0,
                        }

                    if use_streaming:
                        response_data = curl_client.parse_sse_response(
                            result["text"]
                        )
                    else:
                        response_data = result["data"]
                else:
                    # aiohttp: прямое подключение к API или фоллбек
                    await self._ensure_session()
                    timeout = aiohttp.ClientTimeout(
                        total=self.config.claude_vision_timeout,
                        sock_connect=30,
                    )
                    async with self._session.post(
                        api_url,
                        json=payload,
                        headers=headers,
                        timeout=timeout,
                        proxy=http_proxy,
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            key = self.config.anthropic_api_key or ""
                            logger.error(
                                f"Claude Vision API error: {response.status} - "
                                f"{error_text}. "
                                f"Key prefix: {key[:10]}..., model: {CLAUDE_MODEL}"
                            )
                            if response.status in (401, 403):
                                return {
                                    'success': False,
                                    'error': f'Ошибка авторизации Claude Vision API ({response.status})',
                                    'text': '',
                                    'confidence': 0.0,
                                }
                            if response.status >= 500 or response.status == 429:
                                if attempt < self.config.retries - 1:
                                    await asyncio.sleep(
                                        self.config.retry_delay * (attempt + 1)
                                    )
                                    continue
                            return {
                                'success': False,
                                'error': f'Ошибка Claude Vision API: {response.status}',
                                'text': '',
                                'confidence': 0.0,
                            }

                        if use_streaming:
                            response_data = await self._read_sse_stream(response)
                        else:
                            response_data = await response.json()

                text = self._extract_claude_text(response_data)

                if not text:
                    return {
                        'success': False,
                        'error': 'Текст на изображении не обнаружен',
                        'warning': 'Убедитесь, что фото чёткое и текст хорошо виден',
                        'text': '',
                        'confidence': 0.0,
                    }

                logger.info(
                    f"Claude Vision OCR successful: {len(text)} chars"
                )

                return {
                    'success': True,
                    'text': text,
                    'confidence': 0.95,
                    'corrected': False,
                    'error': None,
                }

            except asyncio.TimeoutError:
                logger.warning(
                    f"Claude Vision API timeout "
                    f"(attempt {attempt + 1}/{self.config.retries})"
                )
                if attempt < self.config.retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                return {
                    'success': False,
                    'error': 'Превышено время ожидания. Попробуйте ещё раз.',
                    'text': '',
                    'confidence': 0.0,
                }

            except aiohttp.ClientError as e:
                logger.error(
                    f"Claude Vision API connection error: {e} "
                    f"(attempt {attempt + 1}/{self.config.retries}, url={api_url})"
                )
                if attempt < self.config.retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                return {
                    'success': False,
                    'error': f'Ошибка подключения к API: {str(e)}',
                    'text': '',
                    'confidence': 0.0,
                }

            except Exception as e:
                logger.error(
                    f"Claude Vision API request error: {e}", exc_info=True
                )
                if attempt < self.config.retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                return {
                    'success': False,
                    'error': f'Ошибка запроса: {str(e)}',
                    'text': '',
                    'confidence': 0.0,
                }

    @staticmethod
    async def _read_sse_stream(response) -> Dict[str, Any]:
        """Читает SSE-поток от Claude API и собирает финальный ответ."""
        text_parts = []
        input_tokens = 0
        output_tokens = 0
        model = ""

        async for line_bytes in response.content:
            line = line_bytes.decode('utf-8', errors='replace').strip()
            if not line.startswith('data: '):
                continue
            data_str = line[6:]  # убираем "data: "
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

        # Собираем в формат, совместимый с _extract_claude_text
        return {
            "content": [{"type": "text", "text": "".join(text_parts)}],
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        }

    @staticmethod
    def _extract_claude_text(response_data: Dict[str, Any]) -> str:
        """Извлечение текста из ответа Claude API."""
        try:
            content_blocks = response_data.get('content', [])
            text_parts = []
            for block in content_blocks:
                if block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
            return '\n'.join(text_parts).strip()
        except Exception as e:
            logger.error(f"Error extracting Claude response: {e}", exc_info=True)
            return ''

    async def _recognize_text(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Распознавание текста из изображения через Yandex Vision API.

        Args:
            image_bytes: Байты изображения

        Returns:
            Результат распознавания
        """
        await self._ensure_session()

        # Кодируем изображение в base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Формируем запрос
        payload = {
            "folderId": self.config.folder_id,
            "analyze_specs": [
                {
                    "content": image_base64,
                    "features": [
                        {
                            "type": "TEXT_DETECTION",
                            "text_detection_config": {
                                "language_codes": ["ru", "en"]  # Русский и английский
                            }
                        }
                    ]
                }
            ]
        }

        headers = {
            "Authorization": f"Api-Key {self.config.api_key}",
            "Content-Type": "application/json"
        }

        # Попытки с retry
        for attempt in range(self.config.retries):
            try:
                async with self._session.post(
                    self.VISION_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=self.config.timeout
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Vision API error: {response.status} - {error_text}")

                        # Специальная обработка ошибки прав доступа
                        if response.status == 403:
                            return {
                                'success': False,
                                'error': 'OCR сервис временно недоступен',
                                'warning': (
                                    'Для работы OCR требуется настроить права доступа в Yandex Cloud.\n'
                                    'Пожалуйста, введите текст вручную.'
                                ),
                                'text': '',
                                'confidence': 0.0
                            }

                        if attempt == self.config.retries - 1:
                            # Для остальных ошибок - общее сообщение
                            error_msg = 'Ошибка сервиса распознавания' if response.status >= 500 else 'Ошибка обработки фото'
                            return {
                                'success': False,
                                'error': error_msg,
                                'text': '',
                                'confidence': 0.0
                            }

                        await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                        continue

                    response_data = await response.json()

                    # Извлекаем текст
                    text, confidence = self._extract_text_from_response(response_data)

                    if not text:
                        return {
                            'success': False,
                            'error': 'Текст на изображении не обнаружен',
                            'warning': 'Убедитесь, что фото четкое и текст хорошо виден',
                            'text': '',
                            'confidence': 0.0
                        }

                    logger.info(f"OCR successful: {len(text)} chars, confidence: {confidence:.2f}")

                    return {
                        'success': True,
                        'text': text,
                        'confidence': confidence,
                        'error': None
                    }

            except asyncio.TimeoutError:
                logger.warning(f"Vision API timeout (attempt {attempt + 1}/{self.config.retries})")
                if attempt == self.config.retries - 1:
                    return {
                        'success': False,
                        'error': 'Превышено время ожидания. Попробуйте еще раз.',
                        'text': '',
                        'confidence': 0.0
                    }
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))

            except Exception as e:
                logger.error(f"Vision API request error: {e}", exc_info=True)
                if attempt == self.config.retries - 1:
                    return {
                        'success': False,
                        'error': f'Ошибка запроса: {str(e)}',
                        'text': '',
                        'confidence': 0.0
                    }
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))

    def _extract_text_from_response(self, response_data: Dict[str, Any]) -> tuple[str, float]:
        """
        Извлечение текста из ответа Yandex Vision API.

        Args:
            response_data: Ответ от API

        Returns:
            (text, confidence): Текст и средняя уверенность
        """
        try:
            results = response_data.get('results', [])
            if not results:
                return '', 0.0

            # Получаем результаты распознавания текста
            text_detection = results[0].get('results', [])
            if not text_detection:
                return '', 0.0

            # Первый результат - это полный текст
            text_annotation = text_detection[0].get('textDetection', {})

            # Извлекаем страницы
            pages = text_annotation.get('pages', [])
            if not pages:
                return '', 0.0

            # Собираем текст со всех страниц
            all_text_parts = []
            all_confidences = []

            for page in pages:
                blocks = page.get('blocks', [])

                for block in blocks:
                    lines = block.get('lines', [])

                    for line in lines:
                        words = line.get('words', [])
                        line_text = ' '.join([
                            word.get('text', '') for word in words
                        ])

                        if line_text:
                            all_text_parts.append(line_text)

                            # Собираем confidence для каждого слова
                            for word in words:
                                conf = word.get('confidence', 0.0)
                                if conf > 0:
                                    all_confidences.append(conf)

            # Объединяем текст
            full_text = '\n'.join(all_text_parts)

            # Вычисляем среднюю уверенность
            avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0

            return full_text.strip(), avg_confidence

        except Exception as e:
            logger.error(f"Error extracting text from Vision API response: {e}", exc_info=True)
            return '', 0.0

    async def _correct_ocr_with_llm(
        self,
        ocr_text: str,
        task_context: Optional[str] = None
    ) -> Optional[str]:
        """
        Коррекция распознанного текста с помощью YandexGPT.

        Исправляет типичные ошибки OCR для рукописного русского текста,
        используя предметный контекст (обществознание ЕГЭ) для более
        точной коррекции.

        Args:
            ocr_text: Исходный текст после OCR
            task_context: Контекст задания для улучшения коррекции

        Returns:
            Скорректированный текст или None при ошибке
        """
        try:
            from core.ai_service import get_ai_service

            ai_service = get_ai_service()

            # Базовый контекст предмета
            context_section = ""
            if task_context:
                context_section = (
                    f"\nКОНТЕКСТ ЗАДАНИЯ:\n"
                    f"{task_context}\n"
                    f"Используй этот контекст для более точной коррекции — "
                    f"если слово похоже на термин из данной темы, скорее всего это он и есть.\n"
                )

            system_prompt = (
                "Ты — специалист по коррекции текстов, распознанных с рукописных изображений (OCR). "
                "Тебе дан текст, распознанный с фотографии рукописного ответа ученика на ЕГЭ по обществознанию. "
                "OCR часто допускает серьёзные ошибки при чтении почерка.\n\n"
                "ТВОЯ ЗАДАЧА: Восстановить исходный текст, написанный учеником, "
                "исправив ошибки OCR-распознавания. НЕ меняй смысл и содержание.\n"
                f"{context_section}\n"
                "ПРЕДМЕТ — ОБЩЕСТВОЗНАНИЕ ЕГЭ. Часто встречаемая лексика:\n"
                "- Политика: государство, республика, монархия, демократия, федерация, парламент, "
                "президент, конституция, суверенитет, легитимность, форма правления, "
                "политический режим, авторитаризм, тоталитаризм, унитарное, смешанная республика, "
                "парламентская, президентская, гражданское общество, правовое государство, "
                "разделение властей, законодательная, исполнительная, судебная\n"
                "- Право: правоотношения, правонарушение, правоспособность, дееспособность, "
                "юридическая ответственность, истец, ответчик, уголовное, административное, "
                "гражданское право, конституционное, трудовое, семейное, субъект, объект, "
                "правоприменение, законотворчество, нормативный акт, санкция, диспозиция\n"
                "- Экономика: спрос, предложение, конкуренция, монополия, инфляция, "
                "безработица, ВВП, бюджет, налоги, предпринимательство, собственность, "
                "рыночная экономика, факторы производства, рентабельность, издержки\n"
                "- Социология: социализация, стратификация, мобильность, институт, "
                "социальная группа, социальная норма, девиация, статус, роль, конфликт, "
                "этнос, нация, семья, образование\n"
                "- Философия: познание, мировоззрение, истина, деятельность, сознание, "
                "общество, культура, наука, религия, мораль, глобализация\n\n"
                "ТИПИЧНЫЕ ОШИБКИ OCR ПРИ ЧТЕНИИ РУССКОГО РУКОПИСНОГО ТЕКСТА:\n"
                "- Путаница похожих букв: м↔ш (\"Сметанная\"→\"Смешанная\"), "
                "п↔н, и↔н, т↔г, е↔с, а↔о, ь↔б, з↔э, ц↔щ, к↔н, д↔л, в↔б, р↔г, ж↔к, "
                "у↔ч, х↔ж, ы↔м, ъ↔ь, ё↔е, й↔и\n"
                "- Путаница буквосочетаний: ш↔iii, щ↔шi, м↔iii, ни↔ш, ни↔пи, лн↔ш, "
                "ст↔от, ча↔на, уча↔насто, лл↔пл, рр↔гг\n"
                "- Склеивание или разрыв слов\n"
                "- Пропуск букв, особенно в окончаниях\n"
                "- Замена строчных на прописные и наоборот\n"
                "- Путаница цифр: 1↔7, 4↔9, 3↔8, 6↔0\n\n"
                "ПРАВИЛА:\n"
                "1. Каждое слово проверяй на осмысленность — если слово не существует "
                "или не подходит по контексту, найди ближайшее по начертанию осмысленное слово\n"
                "2. Используй контекст предложения и тему задания для выбора правильного варианта\n"
                "3. НЕ добавляй новую информацию, НЕ дописывай ответ за ученика\n"
                "4. НЕ улучшай грамматику автора — исправляй только артефакты OCR\n"
                "5. Сохраняй оригинальную структуру (абзацы, нумерацию, переносы строк)\n"
                "6. Ответ должен содержать ТОЛЬКО исправленный текст, без пояснений"
            )

            prompt = (
                f"Исправь ошибки OCR-распознавания в следующем рукописном тексте ученика. "
                f"Верни ТОЛЬКО исправленный текст:\n\n{ocr_text}"
            )

            result = await ai_service.get_completion(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=len(ocr_text) * 2 + 200
            )

            if result.get('success') and result.get('text'):
                corrected = result['text'].strip()
                # Проверяем что LLM не вернул пустоту и не слишком изменил текст
                if corrected and len(corrected) > len(ocr_text) * 0.3:
                    logger.info(
                        f"LLM OCR correction: {len(ocr_text)} -> {len(corrected)} chars"
                    )
                    return corrected
                else:
                    logger.warning("LLM returned too short correction, keeping original")
                    return None
            else:
                logger.warning(f"LLM correction failed: {result.get('error', 'unknown')}")
                return None

        except Exception as e:
            logger.error(f"LLM OCR correction error: {e}", exc_info=True)
            return None


# Глобальный экземпляр сервиса
_vision_service_instance: Optional[VisionService] = None


def get_vision_service() -> VisionService:
    """Получение глобального экземпляра сервиса"""
    global _vision_service_instance

    if _vision_service_instance is None:
        _vision_service_instance = VisionService()

    return _vision_service_instance


# Вспомогательная функция для обработки фото в обработчиках
async def process_photo_message(
    update,
    bot: Bot,
    task_name: str = "ответ",
    task_context: Optional[str] = None
) -> Optional[str]:
    """
    Удобная функция для обработки фотографий в обработчиках.

    Поддерживает предобработку изображений и LLM-коррекцию
    для улучшения распознавания рукописного текста.

    Args:
        update: Update объект
        bot: Bot объект
        task_name: Название задания для сообщений
        task_context: Предметный контекст для улучшения OCR-коррекции
            (например: "ЕГЭ обществознание, задание 19, тема: Формы государства")

    Returns:
        Распознанный текст или None при ошибке
    """
    if not update.message or not update.message.photo:
        return None

    vision_service = get_vision_service()

    if not vision_service.is_available:
        await update.message.reply_text(
            "❌ Функция распознавания текста с фото недоступна.\n"
            "Пожалуйста, введите ответ текстом или загрузите документ (PDF, DOCX, TXT)."
        )
        return None

    # Берем самое большое фото (лучшее качество)
    photo = update.message.photo[-1]

    # Показываем процесс
    processing_msg = await update.message.reply_text(
        "📸 Распознаю рукописный текст с фотографии...\n"
        "Обработка изображения и распознавание."
    )

    try:
        # Обрабатываем фото
        result = await vision_service.process_telegram_photo(photo, bot, task_context=task_context)

        # Удаляем сообщение о обработке
        try:
            await processing_msg.delete()
        except Exception:
            pass

        if not result['success']:
            error_msg = result.get('error', 'Неизвестная ошибка')
            warning_msg = result.get('warning', '')

            full_msg = f"❌ {error_msg}"
            if warning_msg:
                full_msg += f"\n\n💡 {warning_msg}"

            full_msg += f"\n\nПопробуйте:\n• Сделать фото при лучшем освещении\n• Убедиться, что текст четкий\n• Ввести {task_name} текстом"

            await update.message.reply_text(full_msg)
            return None

        # Успешно распознали
        text = result['text']
        confidence = result['confidence']
        corrected = result.get('corrected', False)

        # Формируем сообщение с предпросмотром
        if len(text) > 500:
            preview = text[:500] + "..."
        else:
            preview = text

        # Экранируем HTML-символы для безопасного отображения
        preview_escaped = html.escape(preview)

        confidence_emoji = "✅" if confidence > 0.8 else "⚠️" if confidence > 0.5 else "❌"
        confidence_text = f"{confidence * 100:.0f}%"

        correction_note = ""
        if corrected:
            correction_note = "\n🔧 <i>Текст скорректирован AI для исправления ошибок распознавания</i>\n"

        await update.message.reply_text(
            f"✅ Текст распознан!\n\n"
            f"📝 <b>Распознанный текст (предпросмотр):</b>\n"
            f"<code>{preview_escaped}</code>\n\n"
            f"{confidence_emoji} <b>Уверенность OCR:</b> {confidence_text}"
            f"{correction_note}\n\n"
            f"🔍 Проверяю {task_name}...",
            parse_mode='HTML'
        )

        return text

    except Exception as e:
        logger.error(f"Error in process_photo_message: {e}", exc_info=True)

        try:
            await processing_msg.delete()
        except Exception:
            pass

        await update.message.reply_text(
            f"❌ Ошибка при обработке фото: {str(e)}\n\n"
            f"Пожалуйста, попробуйте еще раз или введите {task_name} текстом."
        )
        return None
