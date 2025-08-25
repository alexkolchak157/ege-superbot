# payment/subscription_manager.py - ИСПРАВЛЕННАЯ версия под ваш API
"""Менеджер подписок с поддержкой модульной системы."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from decimal import Decimal
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
        # ДОБАВИТЬ ЭТУ СТРОКУ:
        self.database_file = DATABASE_FILE  # Используем импортированный DATABASE_FILE
        logger.info(f"SubscriptionManager initialized with mode: {self.subscription_mode}")
    
    @property
    def config(self):
        """Совместимость со старым кодом."""
        return {'SUBSCRIPTION_MODE': self.subscription_mode}

    async def get_failed_renewals(self, hours: int = 24) -> List[Dict]:
        """Получает список неудачных попыток автопродления."""
        try:
            from datetime import datetime, timedelta, timezone
            
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            async with aiosqlite.connect(self.database_file) as conn:
                conn.row_factory = aiosqlite.Row
                
                cursor = await conn.execute("""
                    SELECT DISTINCT
                        ars.user_id,
                        ars.failures_count,
                        ars.recurrent_token,
                        ars.last_renewal_attempt
                    FROM auto_renewal_settings ars
                    WHERE 
                        ars.enabled = 1
                        AND ars.failures_count > 0
                        AND ars.failures_count < 3
                        AND ars.last_renewal_attempt >= ?
                """, (since,))
                
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting failed renewals: {e}")
            return []

    async def increment_renewal_failures(self, user_id: int):
        """Увеличивает счетчик неудачных попыток автопродления."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET failures_count = failures_count + 1,
                        last_renewal_attempt = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (user_id,))
                
                # Проверяем, не превышен ли лимит
                cursor = await conn.execute("""
                    SELECT failures_count FROM auto_renewal_settings WHERE user_id = ?
                """, (user_id,))
                
                row = await cursor.fetchone()
                if row and row[0] >= 3:
                    # Отключаем автопродление после 3 неудач
                    await self.disable_auto_renewal(user_id)
                    logger.warning(f"Auto-renewal disabled for user {user_id} after 3 failures")
                
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error incrementing renewal failures: {e}")

    async def reset_renewal_failures(self, user_id: int):
        """Сбрасывает счетчик неудачных попыток."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET failures_count = 0
                    WHERE user_id = ?
                """, (user_id,))
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error resetting renewal failures: {e}")

    async def update_next_renewal_date(self, user_id: int):
        """Обновляет дату следующего автопродления."""
        try:
            from datetime import datetime, timedelta, timezone
            
            next_date = datetime.now(timezone.utc) + timedelta(days=30)
            
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET next_renewal_date = ?
                    WHERE user_id = ?
                """, (next_date, user_id))
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error updating next renewal date: {e}")

    async def get_user_email(self, user_id: int) -> str:
        """Получает email пользователя."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                cursor = await conn.execute("""
                    SELECT email FROM users WHERE user_id = ?
                """, (user_id,))
                
                row = await cursor.fetchone()
                return row[0] if row else f"user{user_id}@example.com"
                
        except Exception as e:
            logger.error(f"Error getting user email: {e}")
            return f"user{user_id}@example.com"

    async def get_auto_renewal_status(self, user_id: int) -> Optional[Dict]:
        """Получает статус автопродления для пользователя."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute("""
                    SELECT * FROM auto_renewal_settings WHERE user_id = ?
                """, (user_id,))
                
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            logger.error(f"Error getting auto-renewal status: {e}")
            return None

    async def get_last_payment_info(self, user_id: int) -> Optional[Dict]:
        """Получает информацию о последнем платеже пользователя."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute("""
                    SELECT order_id, plan_id, amount, status, metadata, created_at
                    FROM payments 
                    WHERE user_id = ? AND status = 'completed'
                    ORDER BY created_at DESC 
                    LIMIT 1
                """, (user_id,))
                
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    # Парсим metadata если есть
                    if row['metadata']:
                        try:
                            metadata = json.loads(row['metadata'])
                            result['recurrent_id'] = metadata.get('recurrent_token')
                        except json.JSONDecodeError:
                            pass
                    return result
                return None
                
        except Exception as e:
            logger.error(f"Error getting last payment info: {e}")
            return None

    async def get_last_subscription_info(self, user_id: int) -> Optional[Dict]:
        """Получает информацию о последней подписке пользователя."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                conn.row_factory = aiosqlite.Row
                
                if self.subscription_mode == 'modular':
                    # Для модульной системы получаем последние активные модули
                    cursor = await conn.execute("""
                        SELECT plan_id, expires_at 
                        FROM module_subscriptions 
                        WHERE user_id = ? 
                        ORDER BY expires_at DESC 
                        LIMIT 1
                    """, (user_id,))
                else:
                    # Для единой системы
                    cursor = await conn.execute("""
                        SELECT plan_id, expires_at 
                        FROM user_subscriptions 
                        WHERE user_id = ? 
                        ORDER BY activated_at DESC 
                        LIMIT 1
                    """, (user_id,))
                
                row = await cursor.fetchone()
                if row:
                    plan_id = row['plan_id']
                    
                    # Получаем информацию о плане
                    from .config import SUBSCRIPTION_PLANS, MODULE_PLANS
                    
                    plan = None
                    if self.subscription_mode == 'modular':
                        plan = MODULE_PLANS.get(plan_id)
                    if not plan:
                        plan = SUBSCRIPTION_PLANS.get(plan_id)
                    
                    if plan:
                        return {
                            'plan_id': plan_id,
                            'plan_name': plan.get('name', plan_id),
                            'amount': plan.get('price_rub', 0),
                            'expires_at': row['expires_at']
                        }
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting last subscription info: {e}")
            return None

    async def save_user_email(self, user_id: int, email: str) -> bool:
        """Сохраняет email пользователя."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (user_id, email))
                await conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving user email: {e}")
            return False

    async def get_users_for_auto_renewal(self) -> List[Dict]:
        """Получает список пользователей для автопродления."""
        try:
            from datetime import datetime, timezone
            
            async with aiosqlite.connect(self.database_file) as conn:
                conn.row_factory = aiosqlite.Row
                
                cursor = await conn.execute("""
                    SELECT 
                        ars.user_id,
                        ars.recurrent_token,
                        ms.plan_id,
                        p.amount / 100 as amount
                    FROM auto_renewal_settings ars
                    INNER JOIN module_subscriptions ms ON ars.user_id = ms.user_id
                    LEFT JOIN (
                        SELECT user_id, plan_id, MAX(amount) as amount
                        FROM payments
                        WHERE status = 'completed'
                        GROUP BY user_id, plan_id
                    ) p ON ars.user_id = p.user_id
                    WHERE 
                        ars.enabled = 1 
                        AND ars.recurrent_token IS NOT NULL
                        AND ms.is_active = 1
                        AND ms.expires_at <= datetime('now', '+1 day')
                        AND ars.failures_count < 3
                """)
                
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting users for auto-renewal: {e}")
            return []

    async def update_order_payment_id(self, order_id: str, payment_id: str):
        """Обновляет payment_id для заказа.
        
        Args:
            order_id: ID заказа
            payment_id: ID платежа от платежной системы
            
        Returns:
            bool: True если успешно обновлено
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    UPDATE payments 
                    SET payment_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                """, (payment_id, order_id))
                await conn.commit()
                logger.info(f"Updated payment_id for order {order_id}: {payment_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating payment_id: {e}")
            return False
    
    async def save_pending_order(self, order_id: str, user_id: int, plan_id: str, 
                                 amount: int, duration_months: int = 1, 
                                 email: str = None, enable_auto_renewal: bool = False):
        """Сохраняет информацию о pending заказе.
        
        Args:
            order_id: Уникальный ID заказа
            user_id: ID пользователя Telegram
            plan_id: ID плана подписки
            amount: Сумма в рублях
            duration_months: Длительность подписки в месяцах
            email: Email пользователя
            enable_auto_renewal: Флаг автопродления
            
        Returns:
            bool: True если успешно сохранено
        """
        try:
            import json
            
            metadata = json.dumps({
                'plan_id': plan_id,
                'duration_months': duration_months,
                'email': email,
                'enable_auto_renewal': enable_auto_renewal
            })
            
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO payments 
                    (order_id, user_id, plan_id, amount_kopecks, status, metadata, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                """, (order_id, user_id, plan_id, amount * 100, metadata))
                await conn.commit()
                
                logger.info(f"Saved pending order: {order_id} for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error saving pending order: {e}")
            return False    

    async def get_payment_by_order_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Получает информацию о платеже по order_id.
        
        Args:
            order_id: ID заказа
            
        Returns:
            Словарь с информацией о платеже или None
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute("""
                    SELECT * FROM payments WHERE order_id = ?
                """, (order_id,))
                
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            logger.error(f"Error getting payment by order_id: {e}")
            return None

    def _extract_modules_from_plan_id(self, plan_id: str) -> List[str]:
        """Извлекает модули из custom plan_id."""
        modules = []
        
        # Убираем префикс custom_
        plan_parts = plan_id.replace('custom_', '')
        
        # Проверяем наличие каждого модуля в имени
        module_mapping = {
            'test_part': 'test_part',
            'test': 'test_part',
            'task19': 'task19',
            'task20': 'task20', 
            'task24': 'task24',
            'task25': 'task25'
        }
        
        for key, module in module_mapping.items():
            if key in plan_parts and module not in modules:
                modules.append(module)
        
        return modules

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

    # Исправленный метод save_payment_info для payment/subscription_manager.py

    async def save_payment_info(self, user_id: int, payment_id: str, order_id: str, 
                               amount: int, plan_id: str, duration: int,
                               email: str, metadata: Dict = None) -> bool:
        """
        Сохраняет информацию о платеже в базу данных.
        
        Args:
            user_id: ID пользователя
            payment_id: ID платежа от Tinkoff
            order_id: Уникальный ID заказа
            amount: Сумма в рублях
            plan_id: ID плана подписки
            duration: Длительность в месяцах
            email: Email пользователя
            metadata: Дополнительные данные (опционально)
        
        Returns:
            True при успешном сохранении
        """
        try:
            import json
            from datetime import datetime
            
            async with aiosqlite.connect(self.database_file) as conn:
                # Сначала проверим структуру таблицы payments
                cursor = await conn.execute("PRAGMA table_info(payments)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                logger.debug(f"Available columns in payments table: {column_names}")
                
                # Сохраняем email пользователя
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    """,
                    (user_id, email)
                )
                
                # Конвертируем metadata в JSON
                metadata_json = json.dumps(metadata or {})
                
                # ИСПРАВЛЕНИЕ: Используем правильное имя столбца amount_kopecks
                # Проверяем, какие столбцы есть в таблице
                if 'amount_kopecks' in column_names:
                    # Используем amount_kopecks (правильное имя)
                    await conn.execute(
                        """
                        INSERT INTO payments (
                            payment_id, order_id, user_id, plan_id, 
                            amount_kopecks, status, created_at, metadata
                        )
                        VALUES (?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, ?)
                        """,
                        (payment_id, order_id, user_id, plan_id, amount * 100, metadata_json)
                    )
                elif 'amount' in column_names:
                    # Если есть столбец amount (старая версия)
                    await conn.execute(
                        """
                        INSERT INTO payments (
                            payment_id, order_id, user_id, plan_id, 
                            amount, status, created_at, metadata
                        )
                        VALUES (?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, ?)
                        """,
                        (payment_id, order_id, user_id, plan_id, amount * 100, metadata_json)
                    )
                else:
                    # Если нет ни того, ни другого - создаем таблицу
                    logger.warning("Column amount/amount_kopecks not found, creating table...")
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS payments (
                            payment_id TEXT PRIMARY KEY,
                            order_id TEXT UNIQUE NOT NULL,
                            user_id INTEGER NOT NULL,
                            plan_id TEXT NOT NULL,
                            amount_kopecks INTEGER NOT NULL,
                            status TEXT DEFAULT 'pending',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            completed_at TIMESTAMP,
                            metadata TEXT DEFAULT '{}',
                            rebill_id TEXT,
                            is_recurrent BOOLEAN DEFAULT 0,
                            auto_renewal_enabled BOOLEAN DEFAULT 0
                        )
                    """)
                    
                    # И сохраняем данные
                    await conn.execute(
                        """
                        INSERT INTO payments (
                            payment_id, order_id, user_id, plan_id, 
                            amount_kopecks, status, created_at, metadata
                        )
                        VALUES (?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, ?)
                        """,
                        (payment_id, order_id, user_id, plan_id, amount * 100, metadata_json)
                    )
                
                # Если включено автопродление, сохраняем эту информацию
                if metadata and metadata.get('enable_auto_renewal'):
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO auto_renewal_consents (
                            user_id, plan_id, amount, period_days,
                            consent_text, consent_checkbox_state,
                            telegram_chat_id, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            user_id, 
                            plan_id, 
                            amount, 
                            duration * 30,
                            f"Согласие на автопродление подписки {plan_id} на сумму {amount} руб. каждые {duration * 30} дней",
                            user_id  # telegram_chat_id = user_id
                        )
                    )
                
                await conn.commit()
                
                logger.info(f"Payment info saved: order_id={order_id}, user_id={user_id}, amount={amount}₽")
                return True
                
        except Exception as e:
            logger.error(f"Error saving payment info: {e}", exc_info=True)
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
                    
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS auto_renewal_settings (
                            user_id INTEGER PRIMARY KEY,
                            enabled BOOLEAN DEFAULT 0,
                            payment_method TEXT,  -- 'card' или 'recurrent_token'
                            recurrent_token TEXT,  -- Токен для рекуррентных платежей
                            card_id TEXT,  -- ID сохраненной карты
                            last_renewal_attempt TIMESTAMP,
                            next_renewal_date TIMESTAMP,
                            failures_count INTEGER DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Таблица истории автопродлений
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS auto_renewal_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            plan_id TEXT NOT NULL,
                            payment_id TEXT,
                            status TEXT NOT NULL,  -- 'success', 'failed', 'cancelled'
                            amount INTEGER NOT NULL,
                            error_message TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES users(user_id)
                        )
                    """)
                    
                    # Таблица для уведомлений об истечении подписки
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS subscription_notifications (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            notification_type TEXT NOT NULL, -- 'expiry_7days', 'expiry_3days', 'expiry_1day', 'expired'
                            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            subscription_end_date TIMESTAMP,
                            UNIQUE(user_id, notification_type, subscription_end_date)
                        )
                    """)
                    
                    await conn.commit()
                    logger.info("Extended subscription tables created")
                    
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
                'task24': '💎 Задание 24',
                'task25': '✍️ Задание 25'
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
    
    async def create_payment(self, user_id: int, plan_id: str, amount_kopecks: int, 
                            duration_months: int = 1, metadata: dict = None) -> Dict[str, Any]:
        """Создает запись о платеже с сохранением метаданных."""
        import uuid
        import json
        order_id = f"ORD_{user_id}_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"
        
        # КРИТИЧЕСКИ ВАЖНО: Подготавливаем метаданные
        payment_metadata = metadata or {}
        payment_metadata['duration_months'] = duration_months
        payment_metadata['plan_id'] = plan_id
        payment_metadata['user_id'] = user_id
        
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute(
                    """
                    INSERT INTO payments (user_id, order_id, plan_id, amount_kopecks, status, metadata, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                    """,
                    (user_id, order_id, plan_id, amount_kopecks, json.dumps(payment_metadata))
                )
                await conn.commit()
                
            logger.info(f"Created payment {order_id} with duration_months={duration_months}")
            
            return {
                'order_id': order_id,
                'user_id': user_id,
                'plan_id': plan_id,
                'amount_kopecks': amount_kopecks,
                'duration_months': duration_months
            }
        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            raise
    
    async def activate_subscription(self, order_id: str, payment_id: str = None) -> bool:
        """Активирует подписку после успешной оплаты."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                # Получаем информацию о платеже
                cursor = await conn.execute(
                    """
                    SELECT user_id, plan_id, metadata, status 
                    FROM payments 
                    WHERE order_id = ?
                    """,
                    (order_id,)
                )
                payment = await cursor.fetchone()
                
                if not payment:
                    logger.error(f"Payment not found for order {order_id}")
                    return False
                
                user_id, plan_id, metadata_str, current_status = payment
                
                # Проверяем, не был ли платеж уже обработан
                if current_status in ['confirmed', 'completed']:
                    logger.warning(f"Payment {order_id} already processed with status {current_status}")
                    return True
                
                # КРИТИЧЕСКИ ВАЖНО: Извлекаем duration_months из metadata
                metadata = {}
                duration_months = 1  # По умолчанию
                
                if metadata_str:
                    try:
                        metadata = json.loads(metadata_str)
                        duration_months = metadata.get('duration_months', 1)
                        logger.info(f"Extracted duration_months={duration_months} from metadata")
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse metadata for order {order_id}")
                else:
                    logger.warning(f"No metadata for order {order_id}, using default duration_months=1")
                
                logger.info(f"Activating subscription: order={order_id}, user={user_id}, plan={plan_id}, months={duration_months}")
                
                # Активируем подписку с правильным сроком
                if plan_id.startswith('custom_'):
                    modules = metadata.get('modules', [])
                    await self._activate_custom_modules(
                        user_id, modules, plan_id, payment_id or order_id,
                        duration_months=duration_months  # Передаем срок!
                    )
                else:
                    if self.subscription_mode == 'modular':
                        await self._activate_modular_subscription(
                            user_id, plan_id, payment_id or order_id,
                            duration_months=duration_months  # Передаем срок!
                        )
                    else:
                        await self._activate_unified_subscription(
                            user_id, plan_id, payment_id or order_id,
                            duration_months=duration_months  # Передаем срок!
                        )
                
                # Обновляем статус платежа
                await conn.execute(
                    """
                    UPDATE payments 
                    SET status = 'confirmed', 
                        payment_id = ?,
                        completed_at = CURRENT_TIMESTAMP 
                    WHERE order_id = ?
                    """,
                    (payment_id or order_id, order_id)
                )
                await conn.commit()
                
                logger.info(f"✅ Subscription activated for {duration_months} months, order {order_id}")
                return True
                
        except Exception as e:
            logger.exception(f"Error activating subscription: {e}")
            return False
    
    async def _activate_custom_modules(self, user_id: int, modules: list, plan_id: str, payment_id: str, duration_months: int = 1):
        """Исправленная версия активации модулей с поддержкой многомесячных подписок."""
        from datetime import datetime, timedelta, timezone
        
        async with aiosqlite.connect(self.database_file) as conn:
            for module_code in modules:
                logger.info(f"Activating module {module_code} for user {user_id} for {duration_months} months")
                
                # Проверяем существующую подписку
                cursor = await conn.execute(
                    """
                    SELECT expires_at FROM module_subscriptions 
                    WHERE user_id = ? AND module_code = ? AND is_active = 1
                    """,
                    (user_id, module_code)
                )
                existing = await cursor.fetchone()
                
                # Вычисляем правильную дату окончания с учетом duration_months
                duration_days = 30 * duration_months  # Приблизительно
                
                if existing:
                    existing_expires = datetime.fromisoformat(existing[0])
                    
                    if existing_expires > datetime.now(timezone.utc):
                        # Продлеваем от текущей даты окончания
                        new_expires = existing_expires + timedelta(days=duration_days)
                        logger.info(f"Extending existing subscription for {module_code} by {duration_months} months to {new_expires}")
                    else:
                        # Активируем заново
                        new_expires = datetime.now(timezone.utc) + timedelta(days=duration_days)
                        logger.info(f"Renewing expired subscription for {module_code} for {duration_months} months")
                    
                    await conn.execute(
                        """
                        UPDATE module_subscriptions 
                        SET expires_at = ?, plan_id = ?, is_active = 1, updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND module_code = ?
                        """,
                        (new_expires, plan_id, user_id, module_code)
                    )
                else:
                    # Создаем новую подписку
                    new_expires = datetime.now(timezone.utc) + timedelta(days=duration_days)
                    
                    await conn.execute(
                        """
                        INSERT INTO module_subscriptions 
                        (user_id, module_code, plan_id, expires_at, is_active, created_at)
                        VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                        """,
                        (user_id, module_code, plan_id, new_expires)
                    )
                    logger.info(f"Created new subscription for {module_code} for {duration_months} months until {new_expires}")
                
                logger.info(f"✅ Module {module_code} activated for user {user_id} for {duration_months} months")
            
            await conn.commit()

    async def init_database(self):
        """Инициализирует базу данных с поддержкой автопродления."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                # Существующие таблицы
                await self._create_existing_tables(conn)
                
                # НОВОЕ: Таблицы для автопродления
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS auto_renewal_settings (
                        user_id INTEGER PRIMARY KEY,
                        enabled BOOLEAN DEFAULT 0,
                        payment_method TEXT CHECK(payment_method IN ('card', 'recurrent')),
                        recurrent_token TEXT,
                        next_renewal_date TIMESTAMP,
                        failures_count INTEGER DEFAULT 0,
                        last_renewal_attempt TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS auto_renewal_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        plan_id TEXT NOT NULL,
                        payment_id TEXT,
                        order_id TEXT,
                        status TEXT CHECK(status IN ('success', 'failed', 'pending')),
                        amount INTEGER,
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Добавляем индексы
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_auto_renewal_next_date 
                    ON auto_renewal_settings(next_renewal_date)
                """)
                
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_renewal_history_user 
                    ON auto_renewal_history(user_id, created_at)
                """)
                
                await conn.commit()
                logger.info("Database initialized with auto-renewal support")
                
        except Exception as e:
            logger.exception(f"Error initializing database: {e}")

    async def save_rebill_id(self, user_id: int, order_id: str, rebill_id: str):
        """Сохраняет RebillId для рекуррентных платежей.
        
        Args:
            user_id: ID пользователя
            order_id: ID заказа
            rebill_id: Токен для рекуррентных платежей
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                # Обновляем RebillId в payments
                await conn.execute("""
                    UPDATE payments 
                    SET rebill_id = ?
                    WHERE order_id = ?
                """, (rebill_id, order_id))
                
                # Сохраняем в auto_renewal_settings
                await conn.execute("""
                    INSERT OR REPLACE INTO auto_renewal_settings
                    (user_id, enabled, payment_method, recurrent_token, last_renewal_attempt, failures_count)
                    VALUES (?, 1, 'recurrent', ?, CURRENT_TIMESTAMP, 0)
                """, (user_id, rebill_id))
                
                await conn.commit()
                logger.info(f"Saved RebillId for user {user_id}, order {order_id}")
                
        except Exception as e:
            logger.error(f"Error saving rebill_id: {e}")

    async def enable_auto_renewal(self, user_id: int, payment_method: str = 'recurrent', 
                                  recurrent_token: str = None) -> bool:
        """Включает автопродление для пользователя.
        
        Args:
            user_id: ID пользователя
            payment_method: Метод оплаты ('recurrent' или 'card')
            recurrent_token: Токен для рекуррентных платежей
            
        Returns:
            bool: True если успешно включено
        """
        try:
            from datetime import datetime, timedelta, timezone
            
            # Получаем дату следующего продления
            subscription = await self.get_active_subscription(user_id)
            if subscription:
                if isinstance(subscription, dict):
                    next_renewal = subscription.get('expires_at')
                else:
                    next_renewal = subscription.expires_at if hasattr(subscription, 'expires_at') else None
            else:
                # Если нет активной подписки, ставим дату через месяц
                next_renewal = datetime.now(timezone.utc) + timedelta(days=30)
            
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO auto_renewal_settings
                    (user_id, enabled, payment_method, recurrent_token, next_renewal_date, failures_count)
                    VALUES (?, 1, ?, ?, ?, 0)
                """, (user_id, payment_method, recurrent_token, next_renewal))
                await conn.commit()
                
                logger.info(f"Auto-renewal enabled for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error enabling auto-renewal: {e}")
            return False
    
    async def disable_auto_renewal(self, user_id: int) -> bool:
        """Отключает автопродление для пользователя."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET enabled = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (user_id,))
                
                await conn.commit()
                logger.info(f"Auto-renewal disabled for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error disabling auto-renewal: {e}")
            return False
    
    async def process_auto_renewal(self, user_id: int) -> bool:
        """Обрабатывает автопродление подписки."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                # Получаем настройки автопродления
                cursor = await conn.execute("""
                    SELECT enabled, payment_method, recurrent_token, card_id 
                    FROM auto_renewal_settings 
                    WHERE user_id = ? AND enabled = 1
                """, (user_id,))
                
                settings = await cursor.fetchone()
                if not settings:
                    logger.info(f"Auto-renewal not enabled for user {user_id}")
                    return False
                
                enabled, payment_method, recurrent_token, card_id = settings
                
                # Получаем информацию о текущей подписке
                subscription = await self.check_active_subscription(user_id)
                if not subscription:
                    # Подписка истекла, пытаемся продлить
                    
                    # Здесь должна быть интеграция с Tinkoff API для рекуррентного платежа
                    # Пример структуры:
                    success = await self._process_recurrent_payment(
                        user_id, 
                        recurrent_token,
                        subscription.get('plan_id'),
                        subscription.get('amount', 0)
                    )
                    
                    if success:
                        # Записываем успешное продление
                        await conn.execute("""
                            INSERT INTO auto_renewal_history 
                            (user_id, plan_id, payment_id, status, amount)
                            VALUES (?, ?, ?, 'success', ?)
                        """, (user_id, subscription['plan_id'], 
                              f"AUTO_{datetime.now().timestamp()}", 
                              subscription['amount']))
                        
                        # Обновляем дату следующего продления
                        next_date = datetime.now(timezone.utc) + timedelta(days=30)
                        await conn.execute("""
                            UPDATE auto_renewal_settings 
                            SET next_renewal_date = ?, failures_count = 0, 
                                last_renewal_attempt = CURRENT_TIMESTAMP 
                            WHERE user_id = ?
                        """, (next_date, user_id))
                    else:
                        # Записываем неудачную попытку
                        await conn.execute("""
                            UPDATE auto_renewal_settings 
                            SET failures_count = failures_count + 1, 
                                last_renewal_attempt = CURRENT_TIMESTAMP 
                            WHERE user_id = ?
                        """, (user_id,))
                        
                        # Если 3 неудачные попытки - отключаем автопродление
                        cursor = await conn.execute(
                            "SELECT failures_count FROM auto_renewal_settings WHERE user_id = ?",
                            (user_id,)
                        )
                        failures = await cursor.fetchone()
                        if failures and failures[0] >= 3:
                            await self.disable_auto_renewal(user_id)
                            # Уведомляем пользователя
                            return False
                    
                    await conn.commit()
                    return success
                    
                return True
                
        except Exception as e:
            logger.error(f"Error processing auto-renewal: {e}")
            return False
    
    async def _process_recurrent_payment(self, user_id: int, recurrent_token: str, 
                                        plan_id: str, amount: int) -> bool:
        """Обрабатывает рекуррентный платеж через Tinkoff API."""
        try:
            from .tinkoff_api import TinkoffAPI
            
            api = TinkoffAPI()
            
            # Создаем рекуррентный платеж
            payment_data = {
                'Amount': amount * 100,  # В копейках
                'OrderId': f"AUTO_{user_id}_{datetime.now().timestamp()}",
                'Description': f'Автопродление подписки {plan_id}',
                'CustomerKey': str(user_id),
                'Recurrent': 'Y',
                'RebillId': recurrent_token
            }
            
            result = await api.init_recurrent_payment(payment_data)
            
            if result.get('Success'):
                payment_id = result.get('PaymentId')
                
                # Подтверждаем платеж
                confirm_result = await api.confirm_payment(payment_id)
                
                if confirm_result.get('Status') == 'CONFIRMED':
                    # Активируем подписку
                    await self.activate_subscription(
                        f"AUTO_{user_id}_{datetime.now().timestamp()}",
                        user_id,
                        plan_id
                    )
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Recurrent payment error: {e}")
            return False
    
    # ============= УВЕДОМЛЕНИЯ =============
    
    async def get_expiring_subscriptions(self, days_before: int) -> List[Dict]:
        """Получает список подписок, истекающих через указанное количество дней."""
        try:
            check_date = datetime.now(timezone.utc) + timedelta(days=days_before)
            check_date_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
            check_date_end = check_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            async with aiosqlite.connect(self.database_file) as conn:
                conn.row_factory = aiosqlite.Row
                
                if self.subscription_mode == 'modular':
                    # Для модульной системы
                    cursor = await conn.execute("""
                        SELECT DISTINCT user_id, MIN(expires_at) as expires_at, 
                               GROUP_CONCAT(module_code) as modules
                        FROM module_subscriptions
                        WHERE is_active = 1 
                        AND expires_at BETWEEN ? AND ?
                        GROUP BY user_id
                    """, (check_date_start, check_date_end))
                else:
                    # Для единой системы
                    cursor = await conn.execute("""
                        SELECT user_id, plan_id, expires_at
                        FROM user_subscriptions
                        WHERE status = 'active'
                        AND expires_at BETWEEN ? AND ?
                    """, (check_date_start, check_date_end))
                
                results = await cursor.fetchall()
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Error getting expiring subscriptions: {e}")
            return []
    
    async def has_notification_sent(self, user_id: int, notification_type: str, 
                                   subscription_end: datetime) -> bool:
        """Проверяет, было ли уже отправлено уведомление."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                cursor = await conn.execute("""
                    SELECT 1 FROM subscription_notifications
                    WHERE user_id = ? 
                    AND notification_type = ?
                    AND DATE(subscription_end_date) = DATE(?)
                """, (user_id, notification_type, subscription_end))
                
                return await cursor.fetchone() is not None
                
        except Exception as e:
            logger.error(f"Error checking notification: {e}")
            return False
    
    async def mark_notification_sent(self, user_id: int, notification_type: str, 
                                    subscription_end: datetime):
        """Отмечает уведомление как отправленное."""
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    INSERT OR IGNORE INTO subscription_notifications
                    (user_id, notification_type, subscription_end_date)
                    VALUES (?, ?, ?)
                """, (user_id, notification_type, subscription_end))
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error marking notification: {e}")

    async def _activate_unified_subscription(self, user_id: int, plan_id: str, 
                                                 payment_id: str, duration_months: int = 1):
        """Расширенная активация единой подписки с учетом срока."""
        from datetime import datetime, timedelta, timezone
        
        duration_days = 30 * duration_months
        expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
        
        async with aiosqlite.connect(self.database_file) as conn:
            # Проверяем существующую активную подписку
            cursor = await conn.execute(
                """
                SELECT expires_at FROM user_subscriptions 
                WHERE user_id = ? AND status = 'active'
                """,
                (user_id,)
            )
            existing = await cursor.fetchone()
            
            if existing:
                existing_expires = datetime.fromisoformat(existing[0])
                if existing_expires > datetime.now(timezone.utc):
                    # Продлеваем от существующей даты
                    expires_at = existing_expires + timedelta(days=duration_days)
                
                # Деактивируем старую подписку
                await conn.execute(
                    "UPDATE user_subscriptions SET status = 'replaced' WHERE user_id = ? AND status = 'active'",
                    (user_id,)
                )
            
            # Создаем новую запись о подписке
            await conn.execute(
                """
                INSERT INTO user_subscriptions 
                (user_id, plan_id, payment_id, status, expires_at, activated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (user_id, plan_id, payment_id, expires_at, datetime.now(timezone.utc))
            )
            await conn.commit()
            logger.info(f"Unified subscription activated for {duration_months} months until {expires_at}")

    
    async def _activate_modular_subscription(self, user_id: int, plan_id: str, 
                                                 payment_id: str, duration_months: int = 1):
        """Расширенная активация модульной подписки с учетом срока."""
        from datetime import datetime, timedelta, timezone
        from .config import SUBSCRIPTION_PLANS
        
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            raise ValueError(f"Unknown plan: {plan_id}")
        
        modules = plan.get('modules', [])
        duration_days = 30 * duration_months
        expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
        
        async with aiosqlite.connect(self.database_file) as conn:
            for module_code in modules:
                # Проверяем существующую подписку
                cursor = await conn.execute(
                    """
                    SELECT expires_at FROM module_subscriptions 
                    WHERE user_id = ? AND module_code = ? AND is_active = 1
                    """,
                    (user_id, module_code)
                )
                existing = await cursor.fetchone()
                
                if existing:
                    existing_expires = datetime.fromisoformat(existing[0])
                    if existing_expires > datetime.now(timezone.utc):
                        # Продлеваем от существующей даты
                        new_expires = existing_expires + timedelta(days=duration_days)
                    else:
                        new_expires = expires_at
                    
                    await conn.execute(
                        """
                        UPDATE module_subscriptions 
                        SET expires_at = ?, plan_id = ?, updated_at = CURRENT_TIMESTAMP 
                        WHERE user_id = ? AND module_code = ?
                        """,
                        (new_expires, plan_id, user_id, module_code)
                    )
                else:
                    # Создаем новую подписку
                    await conn.execute(
                        """
                        INSERT INTO module_subscriptions 
                        (user_id, module_code, plan_id, expires_at, is_active, created_at)
                        VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                        """,
                        (user_id, module_code, plan_id, expires_at)
                    )
            
            await conn.commit()
            logger.info(f"Modular subscription activated for {duration_months} months")
    
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
    
    async def get_payment_by_order_id(self, order_id: str) -> Optional[Dict]:
        """
        Получает информацию о платеже по order_id.
        
        Args:
            order_id: ID заказа
            
        Returns:
            Словарь с информацией о платеже или None
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    """
                    SELECT 
                        payment_id, order_id, user_id, plan_id,
                        amount, status, created_at, completed_at,
                        metadata, rebill_id
                    FROM payments
                    WHERE order_id = ?
                    """,
                    (order_id,)
                )
                row = await cursor.fetchone()
                
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            logger.error(f"Error getting payment by order_id: {e}")
            return None
    
    async def update_payment_status(self, order_id: str, status: str) -> bool:
        """Обновляет статус платежа.
        
        Args:
            order_id: ID заказа
            status: Новый статус ('pending', 'completed', 'failed', 'cancelled')
            
        Returns:
            bool: True если успешно обновлено
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    UPDATE payments 
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                """, (status, order_id))
                await conn.commit()
                
                logger.info(f"Updated payment status for {order_id}: {status}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating payment status: {e}")
            return False


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