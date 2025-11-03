"""
Vision service для распознавания текста с изображений.

Использует Yandex Vision API для OCR.
"""

import os
import logging
import base64
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List
from telegram import PhotoSize, Bot
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VisionConfig:
    """Конфигурация для Yandex Vision API"""
    api_key: str
    folder_id: str
    timeout: int = 30
    retries: int = 3
    retry_delay: float = 2.0

    @classmethod
    def from_env(cls):
        """Создание конфигурации из переменных окружения"""
        # Используем те же ключи что и для YandexGPT
        api_key = os.getenv('YANDEX_GPT_API_KEY')
        folder_id = os.getenv('YANDEX_GPT_FOLDER_ID')

        if not api_key or not folder_id:
            logger.warning(
                "Yandex Vision API credentials not found. "
                "OCR functionality will be disabled. "
                "Set YANDEX_GPT_API_KEY and YANDEX_GPT_FOLDER_ID to enable."
            )
            return None

        timeout = int(os.getenv('YANDEX_VISION_TIMEOUT', '30'))
        retries = int(os.getenv('YANDEX_VISION_RETRIES', '3'))
        retry_delay = float(os.getenv('YANDEX_VISION_RETRY_DELAY', '2.0'))

        return cls(
            api_key=api_key,
            folder_id=folder_id,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay
        )


class VisionService:
    """Сервис для распознавания текста с изображений через Yandex Vision API"""

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
        else:
            logger.info("VisionService initialized successfully with Yandex Vision API")

    @property
    def is_available(self) -> bool:
        """Проверка доступности OCR"""
        return self.config is not None

    async def _ensure_session(self):
        """Создает сессию если её нет"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

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
        bot: Bot
    ) -> Dict[str, Any]:
        """
        Обработка фотографии от Telegram.

        Args:
            photo: Объект фотографии от Telegram
            bot: Экземпляр бота для загрузки фото

        Returns:
            Словарь с результатом обработки:
            {
                'success': bool,
                'text': str,  # Распознанный текст
                'confidence': float,  # Средняя уверенность (0-1)
                'error': str,  # Ошибка если success=False
                'warning': str  # Предупреждение если нужно
            }
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
            photo_bytes = await file.download_as_bytearray()

            # Распознаем текст
            result = await self._recognize_text(photo_bytes)

            return result

        except Exception as e:
            logger.error(f"Error processing photo: {e}", exc_info=True)
            return {
                'success': False,
                'error': f'Ошибка обработки фото: {str(e)}',
                'text': '',
                'confidence': 0.0
            }

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

                        if attempt == self.config.retries - 1:
                            return {
                                'success': False,
                                'error': f'Ошибка API: {response.status}',
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
    task_name: str = "ответ"
) -> Optional[str]:
    """
    Удобная функция для обработки фотографий в обработчиках.

    Args:
        update: Update объект
        bot: Bot объект
        task_name: Название задания для сообщений

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
        "📸 Распознаю текст с фотографии...\n"
        "Это может занять несколько секунд."
    )

    try:
        # Обрабатываем фото
        result = await vision_service.process_telegram_photo(photo, bot)

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

        # Формируем сообщение с предпросмотром
        if len(text) > 500:
            preview = text[:500] + "..."
        else:
            preview = text

        confidence_emoji = "✅" if confidence > 0.8 else "⚠️" if confidence > 0.5 else "❌"
        confidence_text = f"{confidence * 100:.0f}%"

        await update.message.reply_text(
            f"✅ Текст распознан!\n\n"
            f"📝 <b>Распознанный текст (предпросмотр):</b>\n"
            f"<code>{preview}</code>\n\n"
            f"{confidence_emoji} <b>Уверенность:</b> {confidence_text}\n\n"
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
