# payment/config.py
"""Конфигурация модуля оплаты."""
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

# Tinkoff API settings
TINKOFF_TERMINAL_KEY = os.getenv('TINKOFF_TERMINAL_KEY')
TINKOFF_SECRET_KEY = os.getenv('TINKOFF_SECRET_KEY')
TINKOFF_API_URL = 'https://securepay.tinkoff.ru/v2/'

# Webhook settings
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'https://your-domain.com')
WEBHOOK_PATH = '/payment/webhook'

# Admin notifications
PAYMENT_ADMIN_CHAT_ID = int(os.getenv('PAYMENT_ADMIN_CHAT_ID', '0'))

# Subscription plans
SUBSCRIPTION_PLANS = {
    'basic_month': {
        'name': '🥉 Базовая (1 месяц)',
        'description': 'Доступ к боту на 30 дней',
        'price_rub': 299,
        'duration_days': 30,
        'features': [
            '✅ Все тестовые задания',
            '✅ Подробная статистика',
            '✅ До 100 вопросов в день',
            '❌ Приоритетная поддержка'
        ]
    },
    'pro_month': {
        'name': '🥇 Pro (1 месяц)',
        'description': 'Полный доступ на 30 дней',
        'price_rub': 599,
        'duration_days': 30,
        'features': [
            '✅ Все тестовые задания',
            '✅ Подробная статистика',
            '✅ Неограниченные вопросы',
            '✅ Приоритетная поддержка',
            '✅ Экспорт результатов'
        ]
    },
    'pro_ege': {
        'name': '🎓 Pro до ЕГЭ',
        'description': 'Полный доступ до 03.06.2025',
        'price_rub': 1999,
        'duration_until': datetime(2025, 6, 3, tzinfo=timezone.utc),
        'features': [
            '✅ Все функции Pro',
            '✅ Действует до ЕГЭ 2025',
            '✅ Специальные материалы',
            '✅ Групповые разборы'
        ]
    }
}

def get_plan_price_kopecks(plan_id: str) -> int:
    """Возвращает цену плана в копейках."""
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    return plan['price_rub'] * 100

def get_subscription_end_date(plan_id: str) -> datetime:
    """Вычисляет дату окончания подписки для плана."""
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    
    if 'duration_until' in plan:
        return plan['duration_until']
    else:
        return datetime.now(timezone.utc) + timedelta(days=plan['duration_days'])