# payment/tinkoff.py
"""Интеграция с Tinkoff API для приема платежей."""
import hashlib
import json
import logging
from typing import Dict, Any, Optional
import aiohttp
import os

from .config import (
    TINKOFF_TERMINAL_KEY,
    TINKOFF_SECRET_KEY,
    TINKOFF_API_URL,
    WEBHOOK_BASE_URL,
    WEBHOOK_PATH
)

logger = logging.getLogger(__name__)


class TinkoffPayment:
    """Класс для работы с Tinkoff API."""
    
    def __init__(self):
        self.terminal_key = TINKOFF_TERMINAL_KEY
        self.secret_key = TINKOFF_SECRET_KEY
        self.api_url = TINKOFF_API_URL
    
    def calculate_token(self, params: Dict[str, Any]) -> str:
        """Рассчитывает токен для подписи запроса."""
        # Копируем параметры и добавляем пароль
        token_params = params.copy()
        token_params["Password"] = self.secret_key
        
        # Удаляем сложные структуры и сам Token
        for key in ["Receipt", "DATA", "Token"]:
            token_params.pop(key, None)
        
        # Приводим значения к строкам
        processed = {}
        for key, value in token_params.items():
            if value is None:
                continue
            elif isinstance(value, bool):
                processed[key] = str(value).lower()
            else:
                processed[key] = str(value)
        
        # Сортируем и конкатенируем значения
        sorted_values = [v for k, v in sorted(processed.items())]
        values_string = "".join(sorted_values)
        
        # Вычисляем SHA256
        return hashlib.sha256(values_string.encode('utf-8')).hexdigest()
    
    def verify_webhook_token(self, data: Dict[str, Any]) -> bool:
        """Проверяет подпись webhook от Tinkoff."""
        if "Token" not in data:
            logger.warning("No token in webhook data")
            return False
        
        received_token = data["Token"]
        params = data.copy()
        
        # Вычисляем ожидаемый токен
        expected_token = self.calculate_token(params)
        
        is_valid = expected_token == received_token
        if not is_valid:
            logger.warning(f"Invalid webhook token. Expected: {expected_token}, Received: {received_token}")
        
        return is_valid
    
    async def init_payment(
        self,
        order_id: str,
        amount_kopecks: int,
        description: str,
        user_email: str,
        receipt_items: list,
        user_data: Optional[Dict[str, str]] = None,
        bot_username: str = None  # Добавляем параметр
    ) -> Dict[str, Any]:
        """Инициирует платеж в Tinkoff."""
        
        # ИСПРАВЛЕНИЕ: Получаем username бота динамически
        if not bot_username:
            # Попробуйте получить из конфига или переменной окружения
            bot_username = os.getenv("BOT_USERNAME", "ege_superpuper_bot")
        
        # Убираем @ если он есть
        bot_username = bot_username.lstrip('@')
        
        success_deep_link = f"https://t.me/{bot_username}?start=payment_success_{order_id}"
        fail_deep_link = f"https://t.me/{bot_username}?start=payment_fail_{order_id}"
        
        payload = {
            "TerminalKey": self.terminal_key,
            "Amount": amount_kopecks,
            "OrderId": order_id,
            "Description": description[:250],
            "SuccessURL": success_deep_link,
            "FailURL": fail_deep_link,
            "NotificationURL": f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}",
            "Receipt": {
                "Email": user_email,
                "Taxation": "usn_income",
                "Items": receipt_items
            }
        }
        
        # Добавляем пользовательские данные
        if user_data:
            payload["DATA"] = user_data
        
        # Добавляем токен
        payload["Token"] = self.calculate_token(payload)
        
        # Отправляем запрос
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}Init",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    text = await response.text()
                    data = json.loads(text)
                    
                    if response.status == 200 and data.get("Success"):
                        logger.info(f"Payment initiated: {order_id}")
                        return {
                            "success": True,
                            "payment_id": data.get("PaymentId"),
                            "payment_url": data.get("PaymentURL"),
                            "order_id": order_id
                        }
                    else:
                        error = data.get("Message", "Unknown error")
                        logger.error(f"Payment init failed: {error}")
                        return {
                            "success": False,
                            "error": error
                        }
        
        except Exception as e:
            logger.exception(f"Error initiating payment: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_payment_status(self, payment_id: str) -> Optional[str]:
        """Получает статус платежа."""
        payload = {
            "TerminalKey": self.terminal_key,
            "PaymentId": payment_id
        }
        
        payload["Token"] = self.calculate_token(payload)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}GetState",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    data = await response.json()
                    
                    if data.get("Success"):
                        return data.get("Status")
                    else:
                        logger.error(f"Failed to get payment status: {data.get('Message')}")
                        return None
        
        except Exception as e:
            logger.exception(f"Error getting payment status: {e}")
            return None
    
    def build_receipt_item(self, name: str, price_kopecks: int, quantity: int = 1) -> Dict[str, Any]:
        """Создает позицию чека для API."""
        return {
            "Name": name[:64],  # Максимум 64 символа
            "Price": price_kopecks,
            "Quantity": quantity,
            "Amount": price_kopecks * quantity,
            "Tax": "none",  # Без НДС
            "PaymentMethod": "full_prepayment",
            "PaymentObject": "service"
        }