# payment/config.py - Упрощенная конфигурация с двумя тарифами
"""Конфигурация модуля оплаты с пробным периодом и полной подпиской."""
import os
import logging
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ==================== TINKOFF SETTINGS ====================
TINKOFF_TERMINAL_KEY = os.getenv('TINKOFF_TERMINAL_KEY')
TINKOFF_SECRET_KEY = os.getenv('TINKOFF_SECRET_KEY')
TINKOFF_API_URL = 'https://securepay.tinkoff.ru/v2/'

# ==================== WEBHOOK SETTINGS ====================
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'https://your-domain.com')
WEBHOOK_PATH = '/payment/webhook'
WEBHOOK_HOST = '0.0.0.0'
WEBHOOK_PORT = 8080
# Используем WEBHOOK_BASE_URL из окружения вместо хардкода
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"

# ==================== ADMIN SETTINGS ====================
PAYMENT_ADMIN_CHAT_ID = int(os.getenv('PAYMENT_ADMIN_CHAT_ID', '0'))
DATABASE_PATH = 'quiz_async.db'

# ==================== SUBSCRIPTION MODE ====================
SUBSCRIPTION_MODE = 'modular'  # Режим работы
FREE_MODULES = ['test_part']  # Тестовая часть ВСЕГДА бесплатна

logger.info(f"Payment module loaded with SUBSCRIPTION_MODE = {SUBSCRIPTION_MODE}")

# ==================== УПРОЩЕННАЯ СИСТЕМА ПОДПИСОК ====================
MODULE_PLANS = {
    # Пробный период
    'trial_7days': {
        'name': '🎁 Пробный период',
        'description': 'Полный доступ на 7 дней за 1 рубль',
        'detailed_description': [
            '• Доступ ко всем заданиям второй части',
            '• ИИ-проверка каждого ответа',
            '• Персональные рекомендации',
            '• Без ограничений на 7 дней'
        ],
        'price_rub': 1,
        'duration_days': 7,
        'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
        'type': 'trial',
        'features': [
            '✅ Все задания второй части',
            '✅ ИИ-проверка ответов',
            '✅ Полный доступ на неделю',
            '💡 Идеально для знакомства'
        ]
    },
    
    # Полная подписка
    'package_full': {
        'name': '👑 Полная подписка',
        'description': 'Полный доступ ко всем заданиям',
        'price_rub': 249,
        'duration_days': 30,
        'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
        'type': 'package',
        'features': [
            '✅ Все задания второй части с проверкой ИИ',
            '✅ Задание 19 — Примеры и иллюстрации',
            '✅ Задание 20 — Работа с текстом',
            '✅ Задание 24 — Сложный план',
            '✅ Задание 25 — Обоснование с примерами',
            '💡 Максимальные баллы на ЕГЭ!'
        ],
        'detailed_description': [
            '• Задание 19: Научись подбирать идеальные примеры к любой теории',
            '• Задание 20: Пиши аргументы, которые оценят на максимум',
            '• Задание 24: Составляй планы, которые невозможно завалить',
            '• Задание 25: Обосновывай так, чтобы эксперт поставил 6/6',
            '• ИИ проверяет каждое слово как строгий эксперт ФИПИ',
            '• Смотри эталонные ответы и повторяй успех'
        ]
    }
}

# ==================== СКИДКИ ЗА ДЛИТЕЛЬНОСТЬ ====================
# Расчет:
# 1 месяц: 249₽ (без скидки)
# 3 месяца: 672₽ (10% скидка = 224₽/мес, экономия 75₽)
# 6 месяцев: 1270₽ (15% скидка = 212₽/мес, экономия 224₽)

DURATION_DISCOUNTS = {
    1: {
        'multiplier': 1.0,  # Без скидки
        'label': '1 месяц',
        'discount_percent': 0,
        'badge': ''
    },
    3: {
        'multiplier': 2.7,  # 672₽ вместо 747₽ (скидка 10%)
        'label': '3 месяца',
        'discount_percent': 10,
        'badge': '💰 Выгода',
        'savings': 75  # Экономия в рублях
    },
    6: {
        'multiplier': 5.1,  # 1270₽ вместо 1494₽ (скидка 15%)
        'label': '6 месяцев',
        'discount_percent': 15,
        'badge': '🔥 Лучшая цена',
        'savings': 224  # Экономия в рублях
    }
}

# ==================== ВЫБОР АКТИВНОЙ СИСТЕМЫ ====================
SUBSCRIPTION_PLANS = MODULE_PLANS
logger.info(f"Using simplified MODULE_PLANS with {len(MODULE_PLANS)} plans")
logger.info(f"Available plans: {list(SUBSCRIPTION_PLANS.keys())}")

# ==================== ОПИСАНИЯ МОДУЛЕЙ ДЛЯ UI ====================
MODULE_DESCRIPTIONS = {
    'test_part': {
        'emoji': '📝',
        'short_name': 'Тестовая часть',
        'full_name': 'Задания 1-16 (тестовая часть)',
        'description': 'Все задания первой части ЕГЭ с автопроверкой',
        'features': [
            'Более 1000 заданий',
            'Все темы кодификатора',
            'Мгновенная проверка',
            'Подробные объяснения'
        ],
        'is_free': True
    },
    'task19': {
        'emoji': '🎯',
        'short_name': 'Задание 19',
        'full_name': 'Задание 19 — Примеры и иллюстрации',
        'description': 'Научись подбирать убедительные примеры к любой теории',
        'features': [
            'Учись на лучших примерах',
            'ИИ оценит твои примеры',
            'База готовых решений',
            'Рекомендации по улучшению'
        ],
        'is_free': False
    },
    'task20': {
        'emoji': '📖',
        'short_name': 'Задание 20',
        'full_name': 'Задание 20 — Работа с текстом',
        'description': 'Формулируй аргументы, за которые дают максимум баллов',
        'features': [
            'Разбирай тексты как профи',
            'Пиши убедительные суждения',
            'Используй готовые формулировки',
            'ИИ проверит твою логику'
        ],
        'is_free': False
    },
    'task24': {
        'emoji': '💎',
        'short_name': 'Задание 24',
        'full_name': 'Задание 24 — Сложный план',
        'description': 'Составляй планы, которые эксперт не сможет завалить',
        'features': [
            'Структурируй ответы как профи',
            'ИИ проверит каждый пункт',
            'Смотри эталонные планы',
            'Получай оценку как на ЕГЭ'
        ],
        'is_free': False
    },
    'task25': {
        'emoji': '✍️',
        'short_name': 'Задание 25',
        'full_name': 'Задание 25 — Обоснование',
        'description': 'Обосновывай так убедительно, что эксперт поставит 6/6',
        'features': [
            'Подбирай примеры из разных сфер',
            'ИИ оценит твоё обоснование',
            'Конкретизируй точно и чётко',
            'Получай развёрнутую обратную связь'
        ],
        'is_free': False
    }
}

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_plan_price_kopecks(plan_id: str, months: int = 1) -> int:
    """
    Возвращает цену плана в копейках для Tinkoff API.
    
    Args:
        plan_id: ID плана (trial_7days или package_full)
        months: Количество месяцев
    
    Returns:
        Цена в копейках
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    
    base_price = plan['price_rub']
    
    # Для пробного периода всегда 1₽
    if plan_id == 'trial_7days':
        return 100  # 1₽ в копейках
    
    # Применяем множитель для длительности
    if months in DURATION_DISCOUNTS:
        multiplier = DURATION_DISCOUNTS[months]['multiplier']
        total_price = int(base_price * multiplier)
    else:
        total_price = base_price * months
    
    return total_price * 100  # Конвертируем в копейки


def get_subscription_end_date(plan_id: str, months: int = 1) -> datetime:
    """
    Вычисляет дату окончания подписки для плана.
    
    Args:
        plan_id: ID плана
        months: Количество месяцев
        
    Returns:
        Дата окончания подписки
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    
    if plan_id == 'trial_7days':
        return datetime.now(timezone.utc) + timedelta(days=7)
    else:
        days = 30 * months
        return datetime.now(timezone.utc) + timedelta(days=days)


def calculate_subscription_price(plan_id: str, months: int = 1) -> int:
    """
    Рассчитывает цену подписки с учетом срока и скидок.
    
    Args:
        plan_id: ID плана
        months: Количество месяцев
        
    Returns:
        Цена в РУБЛЯХ (не в копейках!)
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    
    base_price = plan['price_rub']
    
    # Для пробного периода всегда 1₽
    if plan_id == 'trial_7days':
        return 1
    
    # Применяем скидки для многомесячных подписок
    if months in DURATION_DISCOUNTS:
        multiplier = DURATION_DISCOUNTS[months]['multiplier']
        total_price = int(base_price * multiplier)
    else:
        total_price = base_price * months
    
    return total_price


def get_plan_modules(plan_id: str) -> List[str]:
    """
    Возвращает список модулей для плана.
    
    Args:
        plan_id: ID плана
        
    Returns:
        Список кодов модулей
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        return []
    
    modules = plan.get('modules', [])
    
    # Добавляем бесплатные модули если их нет
    for free_module in FREE_MODULES:
        if free_module not in modules:
            modules.append(free_module)
    
    return modules


def format_price(price_rub: int) -> str:
    """Форматирует цену для отображения."""
    return f"{price_rub}₽"


def is_module_free(module_code: str) -> bool:
    """Проверяет, является ли модуль бесплатным."""
    return module_code in FREE_MODULES


def get_module_info(module_code: str) -> Dict[str, Any]:
    """
    Возвращает полную информацию о модуле для UI.
    
    Args:
        module_code: Код модуля
        
    Returns:
        Словарь с информацией о модуле
    """
    if module_code in MODULE_DESCRIPTIONS:
        info = MODULE_DESCRIPTIONS[module_code].copy()
        info['price'] = 0 if module_code in FREE_MODULES else None
        return info
    
    # Дефолтная информация
    return {
        'emoji': '📚',
        'short_name': module_code,
        'full_name': module_code,
        'description': 'Модуль',
        'features': [],
        'is_free': module_code in FREE_MODULES,
        'price': 0 if module_code in FREE_MODULES else None
    }


def get_plan_info(plan_id: str) -> Optional[Dict[str, Any]]:
    """
    Возвращает информацию о плане подписки.
    
    Args:
        plan_id: ID плана
        
    Returns:
        Словарь с информацией о плане или None
    """
    return SUBSCRIPTION_PLANS.get(plan_id)


# ==================== LEGACY SUPPORT ====================
# Для обратной совместимости со старым кодом
LEGACY_SUBSCRIPTION_PLANS = {}

# Экспортируем для обратной совместимости
__all__ = [
    'TINKOFF_TERMINAL_KEY',
    'TINKOFF_SECRET_KEY',
    'TINKOFF_API_URL',
    'WEBHOOK_URL',
    'PAYMENT_ADMIN_CHAT_ID',
    'DATABASE_PATH',
    'SUBSCRIPTION_MODE',
    'FREE_MODULES',
    'MODULE_PLANS',
    'SUBSCRIPTION_PLANS',
    'DURATION_DISCOUNTS',
    'MODULE_DESCRIPTIONS',
    'get_plan_price_kopecks',
    'get_subscription_end_date',
    'calculate_subscription_price',
    'get_plan_modules',
    'format_price',
    'is_module_free',
    'get_module_info',
    'get_plan_info'
]