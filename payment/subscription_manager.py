# payment/subscription_manager.py - ИСПРАВЛЕННАЯ версия под ваш API
"""Менеджер подписок с поддержкой модульной системы."""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import json
from functools import wraps
import aiosqlite

# Используем ваши функции из core.db
from core.db import DATABASE_FILE, execute_with_retry
from .config import (
    SUBSCRIPTION_PLANS, 
    get_subscription_end_date,
    get_plan_modules,
    SUBSCRIPTION_MODE
)

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Управление подписками пользователей."""
    
    async def init_tables(self):
        """Инициализирует таблицы в БД."""
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                # Существующие таблицы
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        plan_id TEXT NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT 1,
                        payment_id TEXT,
                        amount_kopecks INTEGER,
                        UNIQUE(user_id, plan_id, expires_at)
                    )
                """)
                
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        order_id TEXT UNIQUE NOT NULL,
                        plan_id TEXT NOT NULL,
                        amount_kopecks INTEGER NOT NULL,
                        status TEXT DEFAULT 'pending',
                        payment_id TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                """)
                
                # Новые таблицы для модульной системы
                if SUBSCRIPTION_MODE == 'modular':
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS module_subscriptions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            module_code TEXT NOT NULL,
                            plan_id TEXT NOT NULL,
                            expires_at TIMESTAMP NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            is_active BOOLEAN DEFAULT 1,
                            is_trial BOOLEAN DEFAULT 0,
                            payment_id TEXT,
                            UNIQUE(user_id, module_code, expires_at)
                        )
                    """)
                    
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS trial_history (
                            user_id INTEGER PRIMARY KEY,
                            trial_activated_at TIMESTAMP,
                            trial_expires_at TIMESTAMP
                        )
                    """)
                        # Создаем таблицу для модульных подписок
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS user_modules (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            module_code TEXT NOT NULL,
                            is_active INTEGER DEFAULT 1,
                            expires_at TEXT,
                            purchase_date TEXT DEFAULT CURRENT_TIMESTAMP,
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, module_code)
                        )
                    """)
                    
                    # Создаем индексы для производительности
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_user_modules_user ON user_modules(user_id)"
                    )
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_user_modules_active ON user_modules(is_active)"
                    )
                    
                    logger.info("User modules table initialized")
                    # Создаем индексы
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_module_subs_user 
                        ON module_subscriptions(user_id)
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_module_subs_expires 
                        ON module_subscriptions(expires_at)
                    """)
                    
                    logger.info("Modular subscription tables created")
                
                await conn.commit()
                logger.info("Payment tables initialized")
                
        except Exception as e:
            logger.exception(f"Error initializing payment tables: {e}")
            raise
    
    async def get_subscription_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получает информацию о подписке для отображения."""
        if SUBSCRIPTION_MODE == 'modular':
            # Модульная система
            modules = await self.get_user_modules(user_id)
            if not modules:
                return None
                
            # Формируем информацию
            module_names = {
                'test_part': '📝 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',
                'task25': '✍️ Задание 25',
                'task24': '💎 Задание 24 (Премиум)'
            }
            
            active_modules = []
            min_expires = None
            
            for module in modules:
                name = module_names.get(module['module_code'], module['module_code'])
                active_modules.append(name)
                
                if min_expires is None or module['expires_at'] < min_expires:
                    min_expires = module['expires_at']
            
            return {
                'type': 'modular',
                'modules': active_modules,
                'expires_at': min_expires,
                'modules_count': len(modules)
            }
        else:
            # Старая система
            subscription = await self.check_active_subscription(user_id)
            if subscription:
                plan = SUBSCRIPTION_PLANS.get(subscription['plan_id'], {})
                return {
                    'type': 'unified',
                    'plan_name': plan.get('name', 'Подписка'),
                    'plan_id': subscription['plan_id'],
                    'expires_at': subscription['expires_at']
                }
            return None    
    
    async def check_active_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Проверяет активную подписку пользователя."""
        if SUBSCRIPTION_MODE == 'modular':
            return await self._check_modular_subscriptions(user_id)
        else:
            return await self._check_unified_subscription(user_id)
    
    async def _check_unified_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Проверка единой подписки (старая система)."""
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                cursor = await conn.execute(
                    """
                    SELECT plan_id, expires_at, created_at
                    FROM subscriptions
                    WHERE user_id = ? AND is_active = 1 AND expires_at > ?
                    ORDER BY expires_at DESC
                    LIMIT 1
                    """,
                    (user_id, datetime.now(timezone.utc))
                )
                row = await cursor.fetchone()
                
                if row:
                    return {
                        'plan_id': row[0],
                        'expires_at': datetime.fromisoformat(row[1]),
                        'created_at': datetime.fromisoformat(row[2])
                    }
                return None
        except Exception as e:
            logger.error(f"Error checking subscription: {e}")
            return None
    
    async def _check_modular_subscriptions(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Проверка модульных подписок."""
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                # Получаем все активные модули
                cursor = await conn.execute(
                    """
                    SELECT DISTINCT module_code, MAX(expires_at) as expires_at
                    FROM module_subscriptions
                    WHERE user_id = ? AND is_active = 1 AND expires_at > ?
                    GROUP BY module_code
                    """,
                    (user_id, datetime.now(timezone.utc))
                )
                modules = await cursor.fetchall()
                
                if not modules:
                    return None
                
                active_modules = [row[0] for row in modules]
                
                # Определяем эквивалентный план
                if set(active_modules) >= {'test_part', 'task19', 'task20', 'task25', 'task24'}:
                    plan_id = 'package_full'
                elif set(active_modules) >= {'task19', 'task20', 'task25'}:
                    plan_id = 'package_second_part'
                else:
                    plan_id = 'custom_modules'
                
                # Берем минимальную дату окончания
                min_expires = min(datetime.fromisoformat(row[1]) for row in modules)
                
                return {
                    'plan_id': plan_id,
                    'expires_at': min_expires,
                    'active_modules': active_modules,
                    'modules_info': {row[0]: datetime.fromisoformat(row[1]) for row in modules}
                }
        except Exception as e:
            logger.error(f"Error checking modular subscriptions: {e}")
            return None
    
    async def check_module_access(self, user_id: int, module_code: str) -> bool:
        """
        Проверяет доступ пользователя к модулю в модульной системе подписок.
        
        Args:
            user_id: ID пользователя
            module_code: Код модуля (task19, task20, etc.)
        
        Returns:
            True если есть доступ, False иначе
        """
        # Админы имеют доступ ко всем модулям
        from core import config
        if hasattr(config, 'ADMIN_IDS'):
            admin_ids = []
            if isinstance(config.ADMIN_IDS, str):
                admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
            elif isinstance(config.ADMIN_IDS, list):
                admin_ids = config.ADMIN_IDS
            
            if user_id in admin_ids:
                logger.info(f"Admin {user_id} has access to module {module_code}")
                return True
        
        # В модульной системе проверяем покупку конкретного модуля
        if self.config.SUBSCRIPTION_MODE == 'modular':
            # Проверяем в таблице user_modules
            result = await conn.fetch_one(
                """SELECT 1 FROM user_modules 
                   WHERE user_id = ? AND module_code = ? AND is_active = 1
                   AND (expires_at IS NULL OR expires_at > datetime('now'))""",
                (user_id, module_code)
            )
            
            if result:
                logger.info(f"User {user_id} has active module subscription for {module_code}")
                return True
            
            # Проверяем общую Pro подписку (дает доступ ко всем модулям)
            subscription = await self.check_active_subscription(user_id)
            if subscription and subscription['plan_id'] in ['pro_month', 'pro_ege']:
                logger.info(f"User {user_id} has Pro subscription, access to {module_code} granted")
                return True
                
        else:
            # В обычном режиме проверяем любую активную подписку
            subscription = await self.check_active_subscription(user_id)
            if subscription:
                return True
        
        logger.info(f"User {user_id} has no access to module {module_code}")
        return False
    
    async def create_payment(self, user_id: int, plan_id: str, amount_kopecks: int) -> Dict[str, Any]:
        """Создает запись о платеже."""
        import uuid
        order_id = f"ORD_{user_id}_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"
        
        try:
            await execute_with_retry(
                """
                INSERT INTO payments (user_id, order_id, plan_id, amount_kopecks)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, order_id, plan_id, amount_kopecks)
            )
            
            return {
                'order_id': order_id,
                'user_id': user_id,
                'plan_id': plan_id,
                'amount_kopecks': amount_kopecks
            }
        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            raise
    
    async def activate_subscription(self, order_id: str, payment_id: str) -> bool:
        """Активирует подписку после успешной оплаты."""
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                # Получаем информацию о платеже
                cursor = await conn.execute(
                    "SELECT user_id, plan_id, amount_kopecks FROM payments WHERE order_id = ?",
                    (order_id,)
                )
                payment = await cursor.fetchone()
                
                if not payment:
                    logger.error(f"Payment not found for order {order_id}")
                    return False
                
                user_id, plan_id, amount = payment
                
                if SUBSCRIPTION_MODE == 'modular':
                    await self._activate_modular_subscription(user_id, plan_id, payment_id)
                else:
                    await self._activate_unified_subscription(user_id, plan_id, payment_id)
                
                # Обновляем статус платежа
                await conn.execute(
                    """
                    UPDATE payments 
                    SET status = 'completed', payment_id = ?, completed_at = ?
                    WHERE order_id = ?
                    """,
                    (payment_id, datetime.now(timezone.utc), order_id)
                )
                
                await conn.commit()
                logger.info(f"Subscription activated for user {user_id}, plan {plan_id}")
                return True
                
        except Exception as e:
            logger.exception(f"Error activating subscription: {e}")
            return False
    
    async def _activate_unified_subscription(self, user_id: int, plan_id: str, payment_id: str):
        """Активация единой подписки."""
        expires_at = get_subscription_end_date(plan_id)
        
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            await conn.execute(
                """
                INSERT INTO subscriptions (user_id, plan_id, expires_at, payment_id)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, plan_id, expires_at, payment_id)
            )
            await conn.commit()
    
    async def _activate_modular_subscription(self, user_id: int, plan_id: str, payment_id: str):
        """Активация модульной подписки."""
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            raise ValueError(f"Unknown plan: {plan_id}")
        
        modules = plan.get('modules', [])
        expires_at = get_subscription_end_date(plan_id)
        is_trial = plan.get('type') == 'trial'
        
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            # Если это пробный период, проверяем историю
            if is_trial:
                cursor = await conn.execute(
                    "SELECT 1 FROM trial_history WHERE user_id = ?",
                    (user_id,)
                )
                if await cursor.fetchone():
                    raise ValueError("Trial already used")
                
                # Записываем использование триала
                await conn.execute(
                    """
                    INSERT INTO trial_history (user_id, trial_activated_at, trial_expires_at)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, datetime.now(timezone.utc), expires_at)
                )
            
            # Активируем каждый модуль
            for module_code in modules:
                # Проверяем существующую подписку
                cursor = await conn.execute(
                    """
                    SELECT expires_at FROM module_subscriptions
                    WHERE user_id = ? AND module_code = ? 
                    AND is_active = 1 AND expires_at > ?
                    ORDER BY expires_at DESC
                    LIMIT 1
                    """,
                    (user_id, module_code, datetime.now(timezone.utc))
                )
                existing = await cursor.fetchone()
                
                # Если есть активная подписка, продлеваем от её окончания
                if existing:
                    start_from = datetime.fromisoformat(existing[0])
                    new_expires = start_from + (expires_at - datetime.now(timezone.utc))
                else:
                    new_expires = expires_at
                
                await conn.execute(
                    """
                    INSERT INTO module_subscriptions 
                    (user_id, module_code, plan_id, expires_at, is_trial, payment_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, module_code, plan_id, new_expires, is_trial, payment_id)
                )
            
            await conn.commit()
    
    async def has_used_trial(self, user_id: int) -> bool:
        """Проверяет, использовал ли пользователь пробный период."""
        if SUBSCRIPTION_MODE != 'modular':
            return False
        
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                cursor = await conn.execute(
                    "SELECT 1 FROM trial_history WHERE user_id = ?",
                    (user_id,)
                )
                return await cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking trial history: {e}")
            return False
    
    async def get_user_modules(self, user_id: int) -> List[Dict[str, Any]]:
        """Получает информацию о модулях пользователя."""
        if SUBSCRIPTION_MODE != 'modular':
            subscription = await self._check_unified_subscription(user_id)
            if subscription:
                modules = get_plan_modules(subscription['plan_id'])
                return [
                    {
                        'module_code': module,
                        'expires_at': subscription['expires_at'],
                        'plan_id': subscription['plan_id']
                    }
                    for module in modules
                ]
            return []
        
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                cursor = await conn.execute(
                    """
                    SELECT module_code, plan_id, expires_at, is_trial
                    FROM module_subscriptions
                    WHERE user_id = ? AND is_active = 1 AND expires_at > ?
                    ORDER BY module_code, expires_at DESC
                    """,
                    (user_id, datetime.now(timezone.utc))
                )
                modules = await cursor.fetchall()
                
                # Группируем по модулям
                module_dict = {}
                for row in modules:
                    module_code = row[0]
                    if module_code not in module_dict:
                        module_dict[module_code] = {
                            'module_code': module_code,
                            'expires_at': datetime.fromisoformat(row[2]),
                            'plan_id': row[1],
                            'is_trial': bool(row[3])
                        }
                
                return list(module_dict.values())
        except Exception as e:
            logger.error(f"Error getting user modules: {e}")
            return []
    
    async def get_payment_by_order_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Получает информацию о платеже по order_id."""
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                cursor = await conn.execute(
                    "SELECT user_id, plan_id, amount_kopecks, status FROM payments WHERE order_id = ?",
                    (order_id,)
                )
                row = await cursor.fetchone()
                
                if row:
                    return {
                        'user_id': row[0],
                        'plan_id': row[1],
                        'amount_kopecks': row[2],
                        'status': row[3]
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting payment: {e}")
            return None
    
    async def update_payment_status(self, order_id: str, status: str):
        """Обновляет статус платежа."""
        try:
            await execute_with_retry(
                "UPDATE payments SET status = ? WHERE order_id = ?",
                (status, order_id)
            )
        except Exception as e:
            logger.error(f"Error updating payment status: {e}")


def requires_subscription(module_code: Optional[str] = None):
    """
    Декоратор для проверки подписки.
    
    Использование:
    @requires_subscription()  # Проверка любой активной подписки
    @requires_subscription('task24')  # Проверка доступа к конкретному модулю
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(update, context):
            user_id = update.effective_user.id
            
            # Получаем менеджер из контекста
            subscription_manager = context.bot_data.get('subscription_manager')
            if not subscription_manager:
                subscription_manager = SubscriptionManager()
            
            # Проверяем подписку
            if module_code:
                # Проверка доступа к конкретному модулю
                has_access = await subscription_manager.check_module_access(user_id, module_code)
                if not has_access:
                    await update.message.reply_text(
                        f"🔒 Для доступа к этой функции необходима подписка.\n\n"
                        f"Используйте /subscribe для оформления."
                    )
                    return
            else:
                # Проверка любой активной подписки
                subscription = await subscription_manager.check_active_subscription(user_id)
                if not subscription:
                    await update.message.reply_text(
                        "🔒 Для использования бота необходима подписка.\n\n"
                        "Используйте /subscribe для оформления."
                    )
                    return
            
            # Выполняем оригинальную функцию
            return await func(update, context)
        
        return wrapper
    return decorator