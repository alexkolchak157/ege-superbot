# payment/config.py - ФИНАЛЬНАЯ версия с корректными формулировками ФИПИ
"""Конфигурация модуля оплаты с точными описаниями заданий ЕГЭ."""
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
WEBHOOK_URL = 'https://xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai/payment-notification'

# ==================== ADMIN SETTINGS ====================
PAYMENT_ADMIN_CHAT_ID = int(os.getenv('PAYMENT_ADMIN_CHAT_ID', '0'))
DATABASE_PATH = 'quiz_async.db'

# ==================== SUBSCRIPTION MODE ====================
SUBSCRIPTION_MODE = os.getenv('SUBSCRIPTION_MODE', 'modular')  # 'unified' или 'modular'
FREE_MODULES = ['test_part']  # Тестовая часть БЕСПЛАТНА

logger.info(f"Payment module loaded with SUBSCRIPTION_MODE = {SUBSCRIPTION_MODE}")

# ==================== СТАРЫЕ ПЛАНЫ (для обратной совместимости) ====================
LEGACY_SUBSCRIPTION_PLANS = {
    'basic_month': {
        'name': '🥉 Базовая (1 месяц)',
        'description': 'Доступ к боту на 30 дней',
        'price_rub': 299,
        'duration_days': 30,
        'modules': ['test_part'],
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
        'modules': ['test_part', 'task19', 'task20', 'task25'],
        'features': [
            '✅ Все тестовые задания',
            '✅ Задания второй части',
            '✅ Неограниченное использование',
            '✅ Приоритетная поддержка'
        ]
    },
    'pro_ege': {
        'name': '👑 Pro до ЕГЭ',
        'description': 'Полный доступ до конца ЕГЭ',
        'price_rub': 1999,
        'duration_until': datetime(2025, 6, 30, tzinfo=timezone.utc),
        'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
        'features': [
            '✅ Все модули до ЕГЭ',
            '✅ Неограниченное использование',
            '✅ Приоритетная поддержка',
            '✅ Гарантия работы до ЕГЭ'
        ]
    }
}

# ==================== НОВАЯ МОДУЛЬНАЯ СИСТЕМА С КОРРЕКТНЫМИ ФОРМУЛИРОВКАМИ ====================
MODULE_PLANS = {
    # Отдельные модули с точными описаниями по ФИПИ
    'module_test': {
        'name': '📝 Тестовая часть',
        'description': 'Задания 1-16 с автопроверкой',
        'detailed_description': [
            '• Все задания первой части ЕГЭ',
            '• Мгновенная проверка ответов',
            '• Подробные объяснения решений',
            '• Статистика по темам и прогресс'
        ],
        'price_rub': 0,  # БЕСПЛАТНО!
        'duration_days': 30,
        'modules': ['test_part'],
        'type': 'individual'  # ИСПРАВЛЕНО!
    },
    
    'module_task19': {
        'name': '🎯 Задание 19',
        'description': 'Иллюстрация теоретических положений примерами',
        'detailed_description': [
            '• Приведение примеров социальных объектов, процессов, явлений',
            '• Иллюстрация теоретических положений фактами',
            '• ИИ-проверка с развернутой обратной связью',
            '• База эталонных ответов по всем темам'
        ],
        'price_rub': 199,
        'duration_days': 30,
        'modules': ['task19'],
        'type': 'individual'  # ИСПРАВЛЕНО!
    },
    
    'module_task20': {
        'name': '📖 Задание 20',
        'description': 'Формулирование и аргументация суждений',
        'detailed_description': [
            '• Формулирование оценочных суждений на основе текста',
            '• Аргументация прогностических высказываний',
            '• Объяснение связи примеров с проблематикой текста',
            '• Банк типовых формулировок и клише'
        ],
        'price_rub': 199,
        'duration_days': 30,
        'modules': ['task20'],
        'type': 'individual'  # ИСПРАВЛЕНО!
    },
    
    'module_task24': {
        'name': '💎 Задание 24',
        'description': 'Составление сложного плана',
        'detailed_description': [
            '• Составление сложного плана развёрнутого ответа',
            '• Минимум 3 пункта с детализацией в подпунктах',
            '• Экспертная ИИ-проверка структуры и полноты',
            '• База эталонных планов по всем темам курса'
        ],
        'price_rub': 299,  # Премиум задание
        'duration_days': 30,
        'modules': ['task24'],
        'type': 'individual'  # ИСПРАВЛЕНО!
    },
    
    'module_task25': {
        'name': '✍️ Задание 25',
        'description': 'Обоснование и конкретизация примерами',
        'detailed_description': [
            '• Обоснование теоретического положения',
            '• Приведение трёх примеров из различных сфер',
            '• Конкретизация теоретических положений фактами',
            '• Проверка полноты и корректности примеров'
        ],
        'price_rub': 199,
        'duration_days': 30,
        'modules': ['task25'],
        'type': 'individual'  # ИСПРАВЛЕНО!
    },
    
    # Пакетные предложения
    'package_second': {
        'name': '📚 Пакет «Вторая часть»',
        'description': 'Основные задания с развернутым ответом',
        'price_rub': 499,  # Экономия 98₽
        'duration_days': 30,
        'modules': ['task19', 'task20', 'task25'],
        'type': 'package',
        'features': [
            '✅ Задание 19 — Примеры и иллюстрации',
            '✅ Задание 20 — Работа с текстом',
            '✅ Задание 25 — Обоснование с примерами',
            '💰 Экономия 98₽/мес'
        ],
        'detailed_description': [
            '• Все основные задания второй части',
            '• ИИ-проверка каждого ответа',
            '• Персональные рекомендации',
            '• Доступ к базе эталонных ответов'
        ]
    },
    
    'package_full': {
        'name': '👑 Полный доступ',
        'description': 'Все задания второй части ЕГЭ',
        'price_rub': 799,  # НОВАЯ ЦЕНА! Было 999₽, экономия 97₽
        'duration_days': 30,
        'modules': ['task19', 'task20', 'task24', 'task25'],
        'type': 'package',
        'features': [
            '✅ ВСЕ задания второй части (19-25)',
            '✅ Премиум задание 24 (сложный план)',
            '✅ Приоритетная поддержка эксперта',
            '💰 Экономия 97₽/мес'
        ],
        'detailed_description': [
            '• Полная подготовка к письменной части ЕГЭ',
            '• ИИ-проверка + экспертная поддержка',
            '• Неограниченное количество попыток',
            '• Гарантия повышения баллов'
        ]
    },
    
    # Пробный период
    'trial_7days': {
        'name': '🎁 Пробный период',
        'description': 'Полный доступ на 7 дней',
        'price_rub': 1,
        'duration_days': 7,
        'modules': ['task19', 'task20', 'task24', 'task25'],
        'type': 'trial',
        'features': [
            '✅ Все задания второй части',
            '✅ ИИ-проверка ответов',
            '✅ Без автопродления',
            '⚡ Активация мгновенно'
        ]
    }
}

# ==================== СКИДКИ ЗА ДЛИТЕЛЬНОСТЬ ====================
DURATION_DISCOUNTS = {
    1: {
        'multiplier': 1.0, 
        'label': '1 месяц',
        'discount_percent': 0
    },
    3: {
        'multiplier': 2.7,  # Скидка 10%
        'label': '3 месяца',
        'discount_percent': 10,
        'badge': '🔥 Выгодно'
    },
    6: {
        'multiplier': 5.1,  # Скидка 15%
        'label': '6 месяцев', 
        'discount_percent': 15,
        'badge': '💎 Популярно'
    },
    12: {
        'multiplier': 9.0,  # Скидка 25%
        'label': '12 месяцев',
        'discount_percent': 25,
        'badge': '👑 Максимальная выгода'
    }
}

# ==================== ВЫБОР АКТИВНОЙ СИСТЕМЫ ====================
if SUBSCRIPTION_MODE == 'modular':
    SUBSCRIPTION_PLANS = MODULE_PLANS
    logger.info(f"Using MODULE_PLANS with {len(MODULE_PLANS)} plans")
else:
    SUBSCRIPTION_PLANS = LEGACY_SUBSCRIPTION_PLANS
    logger.info(f"Using LEGACY_SUBSCRIPTION_PLANS with {len(LEGACY_SUBSCRIPTION_PLANS)} plans")

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
        'description': 'Иллюстрация теоретических положений примерами',
        'features': [
            'Приведение примеров',
            'ИИ-проверка ответов',
            'База эталонных решений',
            'Обратная связь'
        ],
        'is_free': False
    },
    'task20': {
        'emoji': '📖',
        'short_name': 'Задание 20',
        'full_name': 'Задание 20 — Работа с текстом',
        'description': 'Формулирование и аргументация суждений',
        'features': [
            'Анализ текста',
            'Формулирование суждений',
            'Банк формулировок',
            'Проверка аргументации'
        ],
        'is_free': False
    },
    'task24': {
        'emoji': '💎',
        'short_name': 'Задание 24',
        'full_name': 'Задание 24 — Сложный план',
        'description': 'Составление сложного плана развёрнутого ответа',
        'features': [
            'Структурирование ответа',
            'Проверка полноты плана',
            'Эталонные планы',
            'Экспертная оценка'
        ],
        'is_free': False
    },
    'task25': {
        'emoji': '✍️',
        'short_name': 'Задание 25',
        'full_name': 'Задание 25 — Обоснование',
        'description': 'Обоснование и конкретизация примерами',
        'features': [
            'Три примера из разных сфер',
            'Проверка обоснования',
            'Конкретизация положений',
            'Детальная обратная связь'
        ],
        'is_free': False
    }
}

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_plan_price_kopecks(plan_id: str, months: int = 1, custom_plan_data: dict = None) -> int:
    """
    Возвращает цену плана в копейках для Tinkoff API.
    
    Args:
        plan_id: ID плана
        months: Количество месяцев
        custom_plan_data: Данные custom плана (если план custom)
    
    Returns:
        Цена в копейках
    """
    # Обработка custom планов
    if plan_id.startswith('custom_') and custom_plan_data:
        base_price = custom_plan_data.get('price_rub', 0)
    else:
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            # Пробуем найти в MODULE_PLANS
            if SUBSCRIPTION_MODE == 'modular':
                plan = MODULE_PLANS.get(plan_id)
            
            if not plan:
                raise ValueError(f"Unknown plan: {plan_id}")
        
        base_price = plan['price_rub']
    
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
        # Пробуем найти в альтернативных планах
        plan = MODULE_PLANS.get(plan_id) or LEGACY_SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            raise ValueError(f"Unknown plan: {plan_id}")
    
    if 'duration_until' in plan:
        return plan['duration_until']
    else:
        days = plan.get('duration_days', 30) * months
        return datetime.now(timezone.utc) + timedelta(days=days)

def calculate_subscription_price(plan_id: str, months: int = 1, custom_plan_data: dict = None) -> int:
    """
    Рассчитывает цену подписки с учетом срока и скидок.
    
    Args:
        plan_id: ID плана
        months: Количество месяцев
        custom_plan_data: Данные custom плана
        
    Returns:
        Цена в копейках
    """
    if plan_id.startswith('custom_') and custom_plan_data:
        base_price = custom_plan_data.get('price_rub', 0)
    else:
        plan = SUBSCRIPTION_PLANS.get(plan_id) or MODULE_PLANS.get(plan_id)
        if not plan:
            raise ValueError(f"Unknown plan: {plan_id}")
        base_price = plan['price_rub']
    
    # Применяем скидки для многомесячных подписок
    if months in DURATION_DISCOUNTS:
        multiplier = DURATION_DISCOUNTS[months]['multiplier']
        total_price = int(base_price * multiplier)
    else:
        total_price = base_price * months
    
    return total_price * 100  # Возвращаем в копейках

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
        plan = MODULE_PLANS.get(plan_id) or LEGACY_SUBSCRIPTION_PLANS.get(plan_id)
    
    if not plan:
        return []
    
    modules = plan.get('modules', [])
    
    # Добавляем бесплатные модули если их нет
    for free_module in FREE_MODULES:
        if free_module not in modules:
            modules.append(free_module)
    
    return modules

def get_module_price(module_code: str) -> int:
    """
    Возвращает цену отдельного модуля.
    
    Args:
        module_code: Код модуля
        
    Returns:
        Цена в рублях
    """
    # Ищем модуль в планах
    for plan_id, plan in MODULE_PLANS.items():
        if plan.get('type') == 'module' and module_code in plan.get('modules', []):
            return plan['price_rub']
    
    # Дефолтные цены
    module_prices = {
        'test_part': 0,  # БЕСПЛАТНО
        'task19': 199,
        'task20': 199,
        'task24': 299,  # Премиум
        'task25': 199
    }
    
    return module_prices.get(module_code, 0)

def get_custom_plan_price(modules: List[str], months: int = 1) -> Dict[str, Any]:
    """
    Рассчитывает цену для кастомного набора модулей.
    
    Args:
        modules: Список модулей
        months: Количество месяцев
        
    Returns:
        Словарь с информацией о цене
    """
    # Фильтруем бесплатные модули
    paid_modules = [m for m in modules if m not in FREE_MODULES]
    
    # Проверяем, не выгоднее ли взять пакет
    if set(paid_modules) == {'task19', 'task20', 'task25'}:
        # Это пакет "Вторая часть"
        return {
            'plan_id': 'package_second',
            'price_rub': MODULE_PLANS['package_second']['price_rub'],
            'is_package': True,
            'savings': 98  # Экономия
        }
    elif set(paid_modules) == {'task19', 'task20', 'task24', 'task25'}:
        # Это полный пакет
        return {
            'plan_id': 'package_full',
            'price_rub': MODULE_PLANS['package_full']['price_rub'],
            'is_package': True,
            'savings': 97  # Экономия
        }
    
    # Считаем индивидуальную цену
    total = sum(get_module_price(m) for m in paid_modules)
    
    # Применяем скидки за длительность
    if months in DURATION_DISCOUNTS:
        multiplier = DURATION_DISCOUNTS[months]['multiplier']
        total_with_discount = int(total * multiplier)
    else:
        total_with_discount = total * months
    
    return {
        'plan_id': f'custom_{"_".join(sorted(paid_modules))}',
        'price_rub': total,
        'total_price': total_with_discount,
        'modules': paid_modules,
        'is_package': False,
        'savings': 0
    }

def format_price(price_rub: int) -> str:
    """Форматирует цену для отображения."""
    return f"{price_rub:,}₽".replace(',', ' ')

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
        info['price'] = get_module_price(module_code)
        return info
    
    # Дефолтная информация
    return {
        'emoji': '📚',
        'short_name': module_code,
        'full_name': module_code,
        'description': 'Модуль',
        'features': [],
        'is_free': module_code in FREE_MODULES,
        'price': get_module_price(module_code)
    }