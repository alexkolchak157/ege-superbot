# payment/config.py - обновленная конфигурация
"""Конфигурация модуля оплаты с поддержкой модульной системы."""
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

# Существующие настройки Tinkoff
TINKOFF_TERMINAL_KEY = os.getenv('TINKOFF_TERMINAL_KEY')
TINKOFF_SECRET_KEY = os.getenv('TINKOFF_SECRET_KEY')
TINKOFF_API_URL = 'https://securepay.tinkoff.ru/v2/'

# Webhook settings
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'https://your-domain.com')
WEBHOOK_PATH = '/payment/webhook'

# Admin notifications
PAYMENT_ADMIN_CHAT_ID = int(os.getenv('PAYMENT_ADMIN_CHAT_ID', '0'))

# Режим работы подписок
SUBSCRIPTION_MODE = os.getenv('SUBSCRIPTION_MODE', 'modular')  # 'unified' или 'modular'

# ========= СТАРЫЕ ПЛАНЫ (для обратной совместимости) =========
LEGACY_SUBSCRIPTION_PLANS = {
    'basic_month': {
        'name': '🥉 Базовая (1 месяц)',
        'description': 'Доступ к боту на 30 дней',
        'price_rub': 299,
        'duration_days': 30,
        'modules': ['test_part'],  # Соответствует только тестовой части
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
        'modules': ['test_part', 'task19', 'task20', 'task25'],  # Без премиум task24
        'features': [
            '✅ Все тестовые задания',
            '✅ Задания второй части',
            '✅ Неограниченные вопросы',
            '✅ Приоритетная поддержка'
        ]
    },
    'pro_ege': {
        'name': '🎓 Pro до ЕГЭ',
        'description': 'Полный доступ до 03.06.2025',
        'price_rub': 1999,
        'duration_until': datetime(2025, 6, 3, tzinfo=timezone.utc),
        'modules': ['test_part', 'task19', 'task20', 'task25', 'task24'],  # Все модули
        'features': [
            '✅ Все функции Pro',
            '✅ Премиум задание 24',
            '✅ Действует до ЕГЭ 2025',
            '✅ Специальные материалы'
        ]
    }
}

# ========= НОВАЯ МОДУЛЬНАЯ СИСТЕМА =========
MODULE_PLANS = {
    # Отдельные модули
    'module_test_part': {
        'name': '📝 Тестовая часть',
        'description': 'Задания 1-16 с разбором',
        'price_rub': 149,
        'duration_days': 30,
        'modules': ['test_part'],
        'type': 'individual'
    },
    'module_task19': {
        'name': '🎯 Задание 19',
        'description': 'Анализ суждений с ИИ',
        'price_rub': 199,
        'duration_days': 30,
        'modules': ['task19'],
        'type': 'individual'
    },
    'module_task20': {
        'name': '📖 Задание 20',
        'description': 'Текст с пропусками',
        'price_rub': 199,
        'duration_days': 30,
        'modules': ['task20'],
        'type': 'individual'
    },
    'module_task25': {
        'name': '✍️ Задание 25',
        'description': 'Эссе с проверкой ИИ',
        'price_rub': 199,
        'duration_days': 30,
        'modules': ['task25'],
        'type': 'individual'
    },
    'module_task24': {
        'name': '💎 Задание 24 (Премиум)',
        'description': 'Планы с экспертной проверкой',
        'price_rub': 399,
        'duration_days': 30,
        'modules': ['task24'],
        'type': 'individual'
    },
    
    # Пакетные предложения
    'package_second_part': {
        'name': '🎯 Пакет "Вторая часть"',
        'description': 'Задания 19, 20, 25',
        'price_rub': 499,
        'duration_days': 30,
        'modules': ['task19', 'task20', 'task25'],
        'type': 'package',
        'savings': 98
    },
    'package_full': {
        'name': '👑 Полный доступ',
        'description': 'Все модули + VIP поддержка',
        'price_rub': 999,
        'duration_days': 30,
        'modules': ['test_part', 'task19', 'task20', 'task25', 'task24'],
        'type': 'package',
        'savings': 346
    },
    
    # Пробный период
    'trial_7days': {
        'name': '🎁 Пробный период',
        'description': '7 дней полного доступа',
        'price_rub': 1,
        'duration_days': 7,
        'modules': ['test_part', 'task19', 'task20', 'task25', 'task24'],
        'type': 'trial',
        'one_time_only': True
    }
}

# Длительность подписок со скидками
DURATION_DISCOUNTS = {
    1: {'multiplier': 1.0, 'label': '1 месяц'},
    3: {'multiplier': 2.7, 'label': '3 месяца (-10%)'},  # 10% скидка
    6: {'multiplier': 4.8, 'label': '6 месяцев (-20%)'}  # 20% скидка
}

# Выбираем активную систему планов
if SUBSCRIPTION_MODE == 'modular':
    SUBSCRIPTION_PLANS = MODULE_PLANS
else:
    SUBSCRIPTION_PLANS = LEGACY_SUBSCRIPTION_PLANS

def get_plan_price_kopecks(plan_id: str, months: int = 1) -> int:
    """Возвращает цену плана в копейках с учетом длительности."""
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    
    base_price = plan['price_rub']
    
    # Применяем множитель для длительности
    if months in DURATION_DISCOUNTS:
        multiplier = DURATION_DISCOUNTS[months]['multiplier']
        total_price = int(base_price * multiplier)
    else:
        total_price = base_price * months
    
    return total_price * 100

def get_subscription_end_date(plan_id: str, months: int = 1) -> datetime:
    """Вычисляет дату окончания подписки для плана."""
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    
    if 'duration_until' in plan:
        return plan['duration_until']
    else:
        days = plan['duration_days'] * months
        return datetime.now(timezone.utc) + timedelta(days=days)

def get_plan_modules(plan_id: str) -> List[str]:
    """Возвращает список модулей для плана."""
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        return []
    return plan.get('modules', [])