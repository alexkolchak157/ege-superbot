"""
Vision service для распознавания текста с изображений.

ВАЖНО: Этот модуль является заглушкой.
Функционал OCR/Vision пока не реализован.
"""

import logging
from typing import Dict, Any, Optional
from telegram import PhotoSize, Bot

logger = logging.getLogger(__name__)


class VisionService:
    """Сервис для распознавания текста с изображений (заглушка)"""

    def __init__(self):
        logger.warning("VisionService initialized as stub - OCR functionality not implemented")

    async def process_telegram_photo(
        self,
        photo: PhotoSize,
        bot: Bot
    ) -> Dict[str, Any]:
        """
        Обработка фотографии от Telegram (заглушка).

        Args:
            photo: Объект фотографии от Telegram
            bot: Экземпляр бота для загрузки фото

        Returns:
            Словарь с результатом обработки
        """
        logger.info("Vision OCR requested but not implemented")

        return {
            'success': False,
            'error': 'Функция распознавания текста с фото временно недоступна',
            'warning': 'Пожалуйста, введите ответ текстом',
            'text': '',
            'confidence': 0.0
        }


# Глобальный экземпляр сервиса
_vision_service_instance: Optional[VisionService] = None


def get_vision_service() -> VisionService:
    """Получение глобального экземпляра сервиса"""
    global _vision_service_instance

    if _vision_service_instance is None:
        _vision_service_instance = VisionService()

    return _vision_service_instance
