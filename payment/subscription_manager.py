# payment/subscription_manager.py - ИСПРАВЛЕННАЯ версия под ваш API
"""Менеджер подписок с поддержкой модульной системы."""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import json
from functools import wraps
from payment.config import SUBSCRIPTION_MODE, SUBSCRIPTION_PLANS
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
    
    def __init__(self):
        """Инициализация менеджера подписок."""
        # Не используем динамический класс, чтобы избежать проблем с pickle
        self.subscription_mode = SUBSCRIPTION_MODE
        logger.info(f"SubscriptionManager initialized with mode: {self.subscription_mode}")
    
    @property
    def config(self):
        """Совместимость со старым кодом."""
        return {'SUBSCRIPTION_MODE': self.subscription_mode}

    async def save_payment_metadata(self, payment_id: str, metadata: dict):
        """Сохраняет метаданные платежа для custom планов.
        
        Args:
            payment_id: ID платежа
            metadata: Словарь с метаданными (modules, duration_months, plan_name и т.д.)
        """
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            # Создаем таблицу если она не существует
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payment_metadata (
                    payment_id TEXT PRIMARY KEY,
                    metadata TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Сохраняем метаданные
            await conn.execute("""
                INSERT OR REPLACE INTO payment_metadata (payment_id, metadata, created_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (payment_id, json.dumps(metadata)))
            
            await conn.commit()
            
            logger.info(f"Saved metadata for payment {payment_id}: {metadata}")

    async def save_payment_info(
        self,
        user_id: int,
        order_id: str,
        plan_id: str,
        amount: int,
        email: str,
        modules: list = None
    ) -> bool:
        """
        Сохраняет информацию о платеже в БД.
        
        Args:
            user_id: ID пользователя
            order_id: Уникальный ID заказа
            plan_id: ID плана подписки (включая custom_xxx для custom планов)
            amount: Сумма в рублях
            email: Email покупателя
            modules: Список модулей для custom планов
            
        Returns:
            True при успешном сохранении
        """
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                # Подготавливаем metadata для custom планов
                metadata = None
                if modules:
                    metadata = json.dumps({
                        'modules': modules,
                        'type': 'custom'
                    })
                
                # НЕ создаем таблицу здесь - она должна быть создана в init_tables()
                # Просто сохраняем данные
                logger.info(f"Saving payment: order_id={order_id}, user_id={user_id}, plan_id={plan_id}, amount={amount}₽")
                
                try:
                    await conn.execute("""
                        INSERT INTO payments (
                            user_id, order_id, plan_id, amount_kopecks, 
                            status, metadata, email, created_at
                        ) VALUES (?, ?, ?, ?, 'pending', ?, ?, CURRENT_TIMESTAMP)
                    """, (user_id, order_id, plan_id, amount * 100, metadata, email))
                    
                except aiosqlite.OperationalError as e:
                    if "no such table" in str(e):
                        # Если таблицы нет, инициализируем её
                        logger.warning("Table 'payments' not found, initializing...")
                        await self.init_tables()
                        
                        # Повторяем попытку
                        await conn.execute("""
                            INSERT INTO payments (
                                user_id, order_id, plan_id, amount_kopecks, 
                                status, metadata, email, created_at
                            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, CURRENT_TIMESTAMP)
                        """, (user_id, order_id, plan_id, amount * 100, metadata, email))
                    else:
                        raise
                
                # Проверяем что сохранилось
                cursor = await conn.execute(
                    "SELECT order_id, plan_id, email FROM payments WHERE order_id = ?",
                    (order_id,)
                )
                saved = await cursor.fetchone()
                if saved:
                    logger.info(f"✅ Payment saved successfully: order={saved[0]}, plan={saved[1]}, email={saved[2]}")
                else:
                    logger.error(f"❌ Payment not found after saving! order_id={order_id}")
                    return False
                
                # Сохраняем email пользователя в отдельную таблицу для истории
                try:
                    await conn.execute("""
                        INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """, (user_id, email))
                except aiosqlite.OperationalError:
                    # Если таблицы нет, создаем
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS user_emails (
                            user_id INTEGER PRIMARY KEY,
                            email TEXT NOT NULL,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    await conn.execute("""
                        INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """, (user_id, email))
                
                await conn.commit()
                
                logger.info(f"✅ Payment info saved: user={user_id}, order={order_id}, plan={plan_id}, amount={amount}₽")
                if modules:
                    logger.info(f"Custom plan modules: {modules}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error saving payment info: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
            
    async def get_user_active_modules(self, user_id: int) -> List[str]:
        """
        Получает список кодов активных модулей пользователя.
        Это алиас для get_user_modules, но возвращает только коды модулей.
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Список кодов активных модулей (например, ['test_part', 'task19'])
        """
        modules = await self.get_user_modules(user_id)
        # Возвращаем только коды модулей
        return [module['module_code'] for module in modules]
        
    async def init_tables(self):
        """Инициализирует таблицы в БД с правильной схемой."""
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                # Создаем таблицу payments с ПРАВИЛЬНОЙ схемой
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        order_id TEXT UNIQUE NOT NULL,
                        plan_id TEXT NOT NULL,
                        amount_kopecks INTEGER NOT NULL,
                        status TEXT DEFAULT 'pending',
                        payment_id TEXT,
                        metadata TEXT,
                        email TEXT,  -- ВАЖНО: колонка email включена в схему
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                """)
                
                # Проверяем и добавляем недостающие колонки для существующих таблиц
                cursor = await conn.execute("PRAGMA table_info(payments)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                # Добавляем недостающие колонки если таблица уже существовала
                if 'metadata' not in column_names:
                    await conn.execute("ALTER TABLE payments ADD COLUMN metadata TEXT")
                    logger.info("Added metadata column to payments table")
                
                if 'email' not in column_names:
                    await conn.execute("ALTER TABLE payments ADD COLUMN email TEXT")
                    logger.info("Added email column to payments table")
                    
                if 'completed_at' not in column_names:
                    await conn.execute("ALTER TABLE payments ADD COLUMN completed_at TIMESTAMP")
                    logger.info("Added completed_at column to payments table")
                
                await conn.commit()
                    
                # Индексы для payments
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_payments_user 
                    ON payments(user_id)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_payments_status 
                    ON payments(status)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_payments_order 
                    ON payments(order_id)
                """)
                
                # Таблица для хранения email пользователей отдельно
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_emails (
                        user_id INTEGER PRIMARY KEY,
                        email TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Для модульного режима
                if self.subscription_mode == 'modular':
                    # Таблица модульных подписок
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS module_subscriptions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            module_code TEXT NOT NULL,
                            plan_id TEXT NOT NULL,
                            expires_at TIMESTAMP NOT NULL,
                            is_active BOOLEAN DEFAULT 1,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, module_code)
                        )
                    """)
                    
                    # Индексы для module_subscriptions
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_module_subs_user 
                        ON module_subscriptions(user_id)
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_module_subs_expires 
                        ON module_subscriptions(expires_at)
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_module_subs_active 
                        ON module_subscriptions(is_active)
                    """)
                    
                    # История пробных периодов
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS trial_history (
                            user_id INTEGER PRIMARY KEY,
                            trial_activated_at TIMESTAMP,
                            trial_expires_at TIMESTAMP
                        )
                    """)
                    
                    logger.info("Modular subscription tables created")
                
                else:
                    # Единая таблица подписок (для обычного режима)
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS user_subscriptions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            plan_id TEXT NOT NULL,
                            expires_at TIMESTAMP NOT NULL,
                            is_active BOOLEAN DEFAULT 1,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id)
                        )
                    """)
                    
                    logger.info("Standard subscription tables created")
                
                await conn.commit()
                logger.info("All tables initialized successfully")
                
        except Exception as e:
            logger.error(f"Error initializing tables: {e}")
            raise
    
    async def deactivate_subscription(self, user_id: int, plan_id: str) -> bool:
        """
        Деактивация подписки пользователя (при возврате средств)
        
        Args:
            user_id: ID пользователя
            plan_id: ID плана подписки
            
        Returns:
            bool: Успешность операции
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Получаем модули, связанные с планом
                modules = self.SUBSCRIPTION_PLANS.get(plan_id, {}).get('modules', [])
                
                if plan_id == 'package_full':
                    # Для полного пакета деактивируем все модули
                    await db.execute("""
                        DELETE FROM user_subscriptions 
                        WHERE user_id = ?
                    """, (user_id,))
                else:
                    # Для остальных планов деактивируем только конкретные модули
                    for module in modules:
                        await db.execute("""
                            DELETE FROM user_subscriptions 
                            WHERE user_id = ? AND module_id = ?
                        """, (user_id, module))
                
                # Обновляем статус в module_subscriptions
                await db.execute("""
                    UPDATE module_subscriptions 
                    SET status = 'refunded', 
                        end_date = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND plan_id = ? AND status = 'active'
                """, (user_id, plan_id))
                
                await db.commit()
                
                logger.info(f"Подписка {plan_id} деактивирована для пользователя {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Ошибка деактивации подписки: {e}")
            return False

    # Добавьте этот метод для получения информации о платеже:
    async def get_payment_by_order_id(self, order_id: str) -> Optional[dict]:
        """Получает информацию о платеже по order_id."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM payments WHERE order_id = ?
                """, (order_id,))
                
                row = await cursor.fetchone()
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"Error getting payment info: {e}")
            return None
    
    async def get_subscription_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получает информацию о подписке пользователя для отображения."""
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
            
            # ИСПРАВЛЕНИЕ: Добавляем поле is_active
            return {
                'type': 'modular',
                'modules': active_modules,
                'expires_at': min_expires,
                'modules_count': len(modules),
                'is_active': True  # Если есть модули, значит подписка активна
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
                    'expires_at': subscription['expires_at'],
                    'is_active': True  # Подписка активна
                }
            return None  # Возвращаем None если подписки нет
    
    async def check_active_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Проверяет активную подписку пользователя."""
        if SUBSCRIPTION_MODE == 'modular':
            return await self._check_modular_subscriptions(user_id)
        else:
            return await self._check_unified_subscription(user_id)
    
    async def _check_unified_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Проверка единой подписки - ИСПРАВЛЕННАЯ версия."""
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                # Проверяем в правильной таблице user_subscriptions
                cursor = await conn.execute(
                    """
                    SELECT plan_id, expires_at, activated_at
                    FROM user_subscriptions
                    WHERE user_id = ? AND status = 'active' AND expires_at > ?
                    ORDER BY expires_at DESC
                    LIMIT 1
                    """,
                    (user_id, datetime.now(timezone.utc))
                )
                row = await cursor.fetchone()
                
                if row:
                    plan_id, expires_at, activated_at = row
                    return {
                        'plan_id': plan_id,
                        'expires_at': datetime.fromisoformat(expires_at),
                        'activated_at': datetime.fromisoformat(activated_at) if activated_at else None,
                        'active_modules': get_plan_modules(plan_id)  # Для совместимости
                    }
                
                # Проверяем также старую таблицу subscriptions для обратной совместимости
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
                    plan_id, expires_at, created_at = row
                    return {
                        'plan_id': plan_id,
                        'expires_at': datetime.fromisoformat(expires_at),
                        'created_at': datetime.fromisoformat(created_at),
                        'active_modules': get_plan_modules(plan_id)
                    }
                
                return None
                
        except Exception as e:
            logger.error(f"Error checking unified subscription: {e}")
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
        Проверяет доступ пользователя к конкретному модулю.
        
        Args:
            user_id: ID пользователя
            module_code: Код модуля (например, 'test_part', 'task19', etc.)
        
        Returns:
            True если есть доступ, False если нет
        """
        logger.info(f"Checking module access for user {user_id}, module {module_code}")
        
        if SUBSCRIPTION_MODE == 'modular':
            try:
                async with aiosqlite.connect(DATABASE_FILE) as conn:
                    # Проверяем в таблице module_subscriptions
                    cursor = await conn.execute(
                        """
                        SELECT id FROM module_subscriptions 
                        WHERE user_id = ? 
                        AND module_code = ? 
                        AND is_active = 1
                        AND expires_at > datetime('now')
                        """,
                        (user_id, module_code)
                    )
                    result = await cursor.fetchone()
                    
                    if result:
                        logger.info(f"User {user_id} has active module subscription for {module_code}")
                        return True
                    
                    # Проверяем общую подписку (некоторые планы дают доступ ко всем модулям)
                    cursor = await conn.execute(
                        """
                        SELECT plan_id FROM user_subscriptions
                        WHERE user_id = ?
                        AND status = 'active'
                        AND expires_at > datetime('now')
                        """,
                        (user_id,)
                    )
                    subscription = await cursor.fetchone()
                    
                    if subscription:
                        plan_id = subscription[0]
                        
                        # Полный доступ
                        if plan_id in ['package_full', 'trial_7days']:
                            logger.info(f"User {user_id} has full access plan: {plan_id}")
                            return True
                        
                        # Пакет "Вторая часть"
                        elif plan_id == 'package_second_part' and module_code in ['task19', 'task20', 'task25']:
                            logger.info(f"User {user_id} has second part package, access to {module_code}")
                            return True
                        
                        # Старые планы pro_month и pro_ege (доступ ко всему кроме task24)
                        elif plan_id in ['pro_month', 'pro_ege'] and module_code != 'task24':
                            logger.info(f"User {user_id} has Pro subscription, access to {module_code} granted")
                            return True
                    
            except Exception as e:
                logger.error(f"Error checking module access: {e}")
                return False
        else:
            # В обычном режиме проверяем любую активную подписку
            subscription = await self.check_active_subscription(user_id)
            return bool(subscription)
        
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
    
    async def activate_subscription(self, order_id: str, payment_id: str = None) -> bool:
        """Активирует подписку после успешной оплаты с поддержкой custom планов."""
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                # Получаем информацию о платеже
                cursor = await conn.execute(
                    "SELECT user_id, plan_id, metadata FROM payments WHERE order_id = ?",
                    (order_id,)
                )
                payment = await cursor.fetchone()
                
                if not payment:
                    logger.error(f"Payment not found for order {order_id}")
                    return False
                
                user_id, plan_id, metadata_str = payment
                logger.info(f"Activating subscription: user={user_id}, plan={plan_id}, metadata={metadata_str}")
                
                # Обработка custom плана
                if plan_id.startswith('custom_'):
                    # Для custom планов берем модули из metadata или из plan_id
                    modules = []
                    
                    if metadata_str:
                        try:
                            import json
                            metadata = json.loads(metadata_str)
                            modules = metadata.get('modules', [])
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse metadata: {metadata_str}")
                    
                    # Если модули не найдены в metadata, пытаемся извлечь из plan_id
                    if not modules:
                        # Например: custom_test_part_task24 -> ['test_part', 'task24']
                        plan_parts = plan_id.replace('custom_', '')
                        
                        # Распознаем модули в имени плана
                        possible_modules = []
                        if 'test_part' in plan_parts:
                            possible_modules.append('test_part')
                        if 'task19' in plan_parts:
                            possible_modules.append('task19')
                        if 'task20' in plan_parts:
                            possible_modules.append('task20')
                        if 'task24' in plan_parts:
                            possible_modules.append('task24')
                        if 'task25' in plan_parts:
                            possible_modules.append('task25')
                        
                        modules = possible_modules
                    
                    if not modules:
                        logger.error(f"No modules found for custom plan {plan_id}")
                        return False
                    
                    logger.info(f"Activating custom plan with modules: {modules}")
                    
                    # Активируем каждый модуль
                    await self._activate_custom_modules(user_id, modules, plan_id, payment_id)
                    
                else:
                    # Стандартная активация для предопределенных планов
                    if SUBSCRIPTION_MODE == 'modular':
                        await self._activate_modular_subscription(user_id, plan_id, payment_id)
                    else:
                        await self._activate_unified_subscription(user_id, plan_id, payment_id)
                
                # Обновляем статус платежа
                await conn.execute(
                    "UPDATE payments SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE order_id = ?",
                    (order_id,)
                )
                await conn.commit()
                
                logger.info(f"✅ Subscription activated for user {user_id}, order {order_id}")
                return True
                
        except Exception as e:
            logger.exception(f"Error activating subscription: {e}")
            return False
    
    async def _activate_custom_modules(self, user_id: int, modules: list, plan_id: str, payment_id: str):
        """Активирует модули для custom плана с возможностью продления."""
        from datetime import datetime, timedelta, timezone
        
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            for module_code in modules:
                logger.info(f"Activating module {module_code} for user {user_id}")
                
                # Проверяем, есть ли уже активная подписка на этот модуль
                cursor = await conn.execute(
                    """
                    SELECT expires_at FROM module_subscriptions 
                    WHERE user_id = ? AND module_code = ? AND is_active = 1
                    """,
                    (user_id, module_code)
                )
                existing = await cursor.fetchone()
                
                if existing:
                    # Если подписка уже есть, продлеваем её
                    existing_expires = datetime.fromisoformat(existing[0])
                    
                    # Если текущая подписка еще активна, добавляем время к ней
                    if existing_expires > datetime.now(timezone.utc):
                        new_expires = existing_expires + timedelta(days=30)
                        logger.info(f"Extending existing subscription for {module_code} to {new_expires}")
                    else:
                        # Если истекла, начинаем с текущего момента
                        new_expires = datetime.now(timezone.utc) + timedelta(days=30)
                        logger.info(f"Renewing expired subscription for {module_code}")
                    
                    # Обновляем существующую запись
                    await conn.execute(
                        """
                        UPDATE module_subscriptions 
                        SET expires_at = ?, plan_id = ?, is_active = 1
                        WHERE user_id = ? AND module_code = ?
                        """,
                        (new_expires, plan_id, user_id, module_code)
                    )
                else:
                    # Создаем новую подписку
                    new_expires = datetime.now(timezone.utc) + timedelta(days=30)
                    
                    # Сначала деактивируем старые неактивные записи
                    await conn.execute(
                        """
                        DELETE FROM module_subscriptions 
                        WHERE user_id = ? AND module_code = ? AND is_active = 0
                        """,
                        (user_id, module_code)
                    )
                    
                    # Вставляем новую запись
                    await conn.execute(
                        """
                        INSERT INTO module_subscriptions 
                        (user_id, module_code, plan_id, expires_at, is_active, created_at)
                        VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                        """,
                        (user_id, module_code, plan_id, new_expires)
                    )
                    logger.info(f"Created new subscription for {module_code} until {new_expires}")
                
                logger.info(f"✅ Module {module_code} activated for user {user_id}")
            
            await conn.commit()
            logger.info(f"All modules activated for user {user_id}")
    
    async def _activate_unified_subscription(self, user_id: int, plan_id: str, payment_id: str):
        """Активация единой подписки - ИСПРАВЛЕННАЯ версия."""
        expires_at = get_subscription_end_date(plan_id)
        
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            # Используем правильную таблицу user_subscriptions
            await conn.execute(
                """
                INSERT INTO user_subscriptions 
                (user_id, plan_id, payment_id, status, expires_at, activated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (user_id, plan_id, payment_id, expires_at, datetime.now(timezone.utc))
            )
            await conn.commit()
            logger.info(f"Unified subscription activated for user {user_id}, plan {plan_id}")
    
    async def _activate_modular_subscription(self, user_id: int, plan_id: str, payment_id: str):
        """Активация модульной подписки для предопределенных планов."""
        from datetime import datetime, timezone
        from .config import SUBSCRIPTION_PLANS, get_subscription_end_date
        
        logger.info(f"Activating modular subscription for user {user_id}, plan {plan_id}")
        
        # Проверяем только предопределенные планы
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            logger.error(f"Unknown plan: {plan_id}")
            raise ValueError(f"Unknown plan: {plan_id}")
        
        modules = plan.get('modules', [])
        logger.info(f"Plan {plan_id} includes modules: {modules}")
        
        expires_at = get_subscription_end_date(plan_id)
        is_trial = plan.get('type') == 'trial'
        now = datetime.now(timezone.utc)
        
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
                    (user_id, now, expires_at)
                )
            
            # Активируем модули
            for module_code in modules:
                # Деактивируем старые подписки на этот модуль
                await conn.execute(
                    """
                    UPDATE module_subscriptions 
                    SET is_active = 0 
                    WHERE user_id = ? AND module_code = ?
                    """,
                    (user_id, module_code)
                )
                
                # Создаем новую подписку
                await conn.execute(
                    """
                    INSERT INTO module_subscriptions 
                    (user_id, module_code, plan_id, expires_at, is_active, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (user_id, module_code, plan_id, expires_at, now)
                )
                
                logger.info(f"Module {module_code} activated for user {user_id}")
            
            await conn.commit()
            logger.info(f"Modular subscription activated: {len(modules)} modules")
    
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