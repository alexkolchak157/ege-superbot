# payment/config.py - обновленная конфигурация
"""Конфигурация модуля оплаты с поддержкой модульной системы."""
import os
import logging
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from dotenv import load_dotenv
load_dotenv()
# Существующие настройки Tinkoff
TINKOFF_TERMINAL_KEY = os.getenv('TINKOFF_TERMINAL_KEY')
TINKOFF_SECRET_KEY = os.getenv('TINKOFF_SECRET_KEY')
TINKOFF_API_URL = 'https://securepay.tinkoff.ru/v2/'

# Webhook settings
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'https://your-domain.com')
WEBHOOK_PATH = '/payment/webhook'
WEBHOOK_HOST = '0.0.0.0'
WEBHOOK_PORT = 8080
# Admin notifications
PAYMENT_ADMIN_CHAT_ID = int(os.getenv('PAYMENT_ADMIN_CHAT_ID', '0'))
DATABASE_PATH = 'quiz_async.db'  # Укажите путь к вашей БД
WEBHOOK_URL = 'https://xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai/payment-notification'

# Режим работы подписок
SUBSCRIPTION_MODE = os.getenv('SUBSCRIPTION_MODE', 'modular')  # 'unified' или 'modular'

logger = logging.getLogger(__name__)
logger.info(f"Payment module loaded with SUBSCRIPTION_MODE = {SUBSCRIPTION_MODE}")
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
    # Индивидуальные модули с правильными описаниями
    'module_test_part': {
        'name': '📝 Тестовая часть',
        'description': 'Задания 1-16 с выбором ответа',
        'detailed_description': [
            '• Задания 1-16 первой части ЕГЭ',
            '• Все темы обществознания',
            '• Автоматическая проверка ответов',
            '• Детальная статистика ошибок'
        ],
        'price_rub': 149,
        'duration_days': 30,
        'modules': ['test_part'],
        'type': 'individual'
    },
    
    'module_task19': {
        'name': '🎯 Задание 19',  
        'description': 'Иллюстрация теоретических положений примерами',
        'detailed_description': [
            '• Приведение примеров социальных объектов, процессов, явлений',
            '• Иллюстрация теоретических положений фактами',
            '• Проверка ИИ с развернутой обратной связью',
            '• База эталонных ответов по всем темам'
        ],
        'price_rub': 199,
        'duration_days': 30,
        'modules': ['task19'],
        'type': 'individual'
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
        'type': 'individual'
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
        'type': 'individual'
    },
    
    'module_task24': {
        'name': '💎 Задание 24',
        'description': 'Составление сложного плана',
        'detailed_description': [
            '• Составление сложного плана развёрнутого ответа',
            '• Минимум 3 пункта с детализацией в подпунктах',
            '• Экспертная проверка структуры и полноты',
            '• База эталонных планов по всем темам курса'
        ],
        'price_rub': 399,
        'duration_days': 30,
        'modules': ['task24'],
        'type': 'individual'
    },
    
    # Пакетные предложения
    'package_second_part': {
        'name': '🎯 Пакет «Вторая часть»',
        'description': 'Задания 19, 20, 25 с проверкой ИИ',
        'price_rub': 499,
        'duration_days': 30,
        'modules': ['task19', 'task20', 'task25'],
        'type': 'package',
        'features': [
            '✅ Задание 19 - Примеры',  # ИСПРАВЛЕНО
            '✅ Задание 20 - Суждения',  # ИСПРАВЛЕНО
            '✅ Задание 25 - Развёрнутый ответ',  # ИСПРАВЛЕНО
            '✅ Экономия 98₽/мес'
        ]
    },
    'package_full': {
        'name': '👑 Полный доступ',
        'description': 'Все модули + премиум функции',
        'price_rub': 999,
        'duration_days': 30,
        'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
        'type': 'package',
        'features': [
            '✅ Все тестовые задания',
            '✅ Все задания второй части',
            '✅ Приоритетная поддержка',
            '✅ Экономия 346₽/мес'
        ]
    },
    
    # Пробный период
    'trial_7days': {
        'name': '🎁 Пробный период',
        'description': 'Полный доступ на 7 дней',
        'price_rub': 1,
        'duration_days': 7,
        'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
        'type': 'trial'
    }
}

# Длительность подписок со скидками
DURATION_DISCOUNTS = {
    1: {'multiplier': 1.0, 'label': '1 месяц'},
    3: {'multiplier': 2.7, 'label': '3 месяца'},
    6: {'multiplier': 5.0, 'label': '6 месяцев'},
    12: {'multiplier': 9.0, 'label': '12 месяцев'}
}

# Выбираем активную систему планов
if SUBSCRIPTION_MODE == 'modular':
    SUBSCRIPTION_PLANS = MODULE_PLANS
    logger.info(f"Using MODULE_PLANS with {len(MODULE_PLANS)} plans")
else:
    SUBSCRIPTION_PLANS = LEGACY_SUBSCRIPTION_PLANS
    logger.info(f"Using LEGACY_SUBSCRIPTION_PLANS with {len(LEGACY_SUBSCRIPTION_PLANS)} plans")

# Для отладки выведем доступные планы
logger.info(f"Available plans: {list(SUBSCRIPTION_PLANS.keys())}")

def get_plan_price_kopecks(plan_id: str, months: int = 1, custom_plan_data: dict = None) -> int:
    """Возвращает цену плана в копейках с учетом длительности.
    
    Args:
        plan_id: ID плана
        months: Количество месяцев
        custom_plan_data: Данные custom плана (если план custom)
    
    Returns:
        Цена в копейках
    """
    # ИСПРАВЛЕНИЕ: Обработка custom планов
    if plan_id.startswith('custom_') and custom_plan_data:
        base_price = custom_plan_data.get('price_rub', 0)
    else:
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            # Пробуем найти в MODULE_PLANS если используется модульная система
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

def calculate_subscription_price(plan_id: str, months: int = 1, custom_plan_data: dict = None) -> int:
    """Рассчитывает цену подписки с учетом срока и скидок."""
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
    """Возвращает список модулей для плана."""
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        return []
    return plan.get('modules', [])