# payment/subscription_manager.py
"""Централизованное управление подписками."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import aiosqlite
from core.db import DATABASE_FILE, execute_with_retry, set_subscription_status

logger = logging.getLogger(__name__)

# Имена таблиц
TABLE_PAYMENTS = 'payments'
TABLE_SUBSCRIPTIONS = 'user_subscriptions'


class SubscriptionManager:
    """Менеджер подписок с транзакционной логикой."""
    
    def __init__(self, db_path: str = DATABASE_FILE):
        self.db_path = db_path
    
    async def init_tables(self):
            """Создает необходимые таблицы для платежей и подписок."""
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    # Включаем поддержку внешних ключей
                    await db.execute("PRAGMA foreign_keys = ON")
                    
                    # Проверяем существование таблиц и их структуру
                    cursor = await db.execute("""
                        SELECT name FROM sqlite_master 
                        WHERE type='table' AND name IN ('payments', 'user_subscriptions')
                    """)
                    existing_tables = [row[0] for row in await cursor.fetchall()]
                    
                    # Таблица платежей
                    if 'payments' not in existing_tables:
                        await db.execute(f'''
                            CREATE TABLE IF NOT EXISTS {TABLE_PAYMENTS} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id INTEGER NOT NULL,
                                order_id TEXT UNIQUE NOT NULL,
                                payment_id TEXT,
                                plan_id TEXT NOT NULL,
                                amount_kopecks INTEGER NOT NULL,
                                status TEXT NOT NULL DEFAULT 'initiated',
                                provider TEXT DEFAULT 'tinkoff',
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                confirmed_at TIMESTAMP,
                                metadata TEXT,
                                FOREIGN KEY (user_id) REFERENCES users(user_id)
                            )
                        ''')
                        logger.info("Created payments table")
                    
                    # Таблица подписок
                    if 'user_subscriptions' not in existing_tables:
                        await db.execute(f'''
                            CREATE TABLE IF NOT EXISTS {TABLE_SUBSCRIPTIONS} (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id INTEGER NOT NULL,
                                plan_id TEXT NOT NULL,
                                payment_id INTEGER,
                                status TEXT NOT NULL DEFAULT 'pending',
                                starts_at TIMESTAMP NOT NULL,
                                expires_at TIMESTAMP NOT NULL,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                activated_at TIMESTAMP,
                                cancelled_at TIMESTAMP,
                                FOREIGN KEY (user_id) REFERENCES users(user_id),
                                FOREIGN KEY (payment_id) REFERENCES {TABLE_PAYMENTS}(id)
                            )
                        ''')
                        logger.info("Created user_subscriptions table")
                    else:
                        # Проверяем наличие колонки status
                        cursor = await db.execute(f"PRAGMA table_info({TABLE_SUBSCRIPTIONS})")
                        columns = await cursor.fetchall()
                        column_names = [col[1] for col in columns]
                        
                        if 'status' not in column_names:
                            logger.error(f"Table {TABLE_SUBSCRIPTIONS} is missing 'status' column!")
                            logger.error("Please run: python fix_db.py to fix the database structure")
                            raise Exception(f"Database structure error: missing 'status' column in {TABLE_SUBSCRIPTIONS}")
                    
                    # Создаем индексы только если таблицы созданы/проверены
                    indices_to_create = []
                    
                    # Проверяем какие индексы уже существуют
                    cursor = await db.execute("""
                        SELECT name FROM sqlite_master 
                        WHERE type='index' AND sql IS NOT NULL
                    """)
                    existing_indices = [row[0] for row in await cursor.fetchall()]
                    
                    # Список необходимых индексов
                    required_indices = [
                        (f'idx_payments_order', f'{TABLE_PAYMENTS}', 'order_id'),
                        (f'idx_payments_user', f'{TABLE_PAYMENTS}', 'user_id'),
                        (f'idx_subscriptions_user', f'{TABLE_SUBSCRIPTIONS}', 'user_id'),
                        (f'idx_subscriptions_status', f'{TABLE_SUBSCRIPTIONS}', 'status'),
                    ]
                    
                    # Создаем только отсутствующие индексы
                    for index_name, table_name, column_name in required_indices:
                        if index_name not in existing_indices:
                            try:
                                await db.execute(
                                    f'CREATE INDEX {index_name} ON {table_name}({column_name})'
                                )
                                logger.debug(f"Created index {index_name}")
                            except Exception as e:
                                # Индекс может уже существовать под другим именем
                                logger.debug(f"Could not create index {index_name}: {e}")
                    
                    await db.commit()
                    logger.info("Payment tables initialized successfully")
                    
            except Exception as e:
                logger.error(f"Error initializing payment tables: {e}")
                if "no such column" in str(e):
                    logger.error("\n" + "="*50)
                    logger.error("DATABASE STRUCTURE ERROR!")
                    logger.error("Please run one of these commands:")
                    logger.error("1. python fix_db.py (to fix the structure)")
                    logger.error("2. python reset_db.py (to reset the database)")
                    logger.error("="*50 + "\n")
                raise
    
    async def create_payment(
        self,
        user_id: int,
        plan_id: str,
        amount_kopecks: int
    ) -> Dict[str, Any]:
        """Создает новый платеж и возвращает order_id."""
        order_id = f"bot_{plan_id}_{user_id}_{uuid.uuid4().hex[:8]}"
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"""INSERT INTO {TABLE_PAYMENTS} 
                    (user_id, order_id, plan_id, amount_kopecks, status)
                    VALUES (?, ?, ?, ?, 'initiated')""",
                (user_id, order_id, plan_id, amount_kopecks)
            )
            payment_id = cursor.lastrowid
            await db.commit()
        
        logger.info(f"Created payment {payment_id} for user {user_id}, plan {plan_id}")
        return {
            'payment_id': payment_id,
            'order_id': order_id,
            'user_id': user_id,
            'plan_id': plan_id,
            'amount_kopecks': amount_kopecks
        }
    
    async def confirm_payment(self, order_id: str, payment_id: str) -> bool:
        """
        Подтверждает платеж и активирует подписку.
        Выполняется транзакционно.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Начинаем транзакцию
                await db.execute('BEGIN')
                
                # 1. Получаем данные платежа
                cursor = await db.execute(
                    f"SELECT id, user_id, plan_id FROM {TABLE_PAYMENTS} WHERE order_id = ?",
                    (order_id,)
                )
                payment = await cursor.fetchone()
                
                if not payment:
                    logger.error(f"Payment not found for order_id: {order_id}")
                    await db.execute('ROLLBACK')
                    return False
                
                internal_payment_id, user_id, plan_id = payment
                
                # 2. Обновляем статус платежа
                await db.execute(
                    f"""UPDATE {TABLE_PAYMENTS} 
                        SET status = 'confirmed', 
                            payment_id = ?,
                            confirmed_at = CURRENT_TIMESTAMP
                        WHERE id = ?""",
                    (payment_id, internal_payment_id)
                )
                
                # 3. Создаем или обновляем подписку
                from .config import get_subscription_end_date
                expires_at = get_subscription_end_date(plan_id)
                
                # Проверяем, есть ли активная подписка
                cursor = await db.execute(
                    f"""SELECT id FROM {TABLE_SUBSCRIPTIONS} 
                        WHERE user_id = ? AND plan_id = ? AND status = 'pending'
                        ORDER BY created_at DESC LIMIT 1""",
                    (user_id, plan_id)
                )
                subscription = await cursor.fetchone()
                
                if subscription:
                    # Активируем существующую подписку
                    await db.execute(
                        f"""UPDATE {TABLE_SUBSCRIPTIONS}
                            SET status = 'active',
                                activated_at = CURRENT_TIMESTAMP,
                                payment_id = ?
                            WHERE id = ?""",
                        (internal_payment_id, subscription[0])
                    )
                else:
                    # Создаем новую подписку
                    await db.execute(
                        f"""INSERT INTO {TABLE_SUBSCRIPTIONS}
                            (user_id, plan_id, payment_id, status, starts_at, expires_at, activated_at)
                            VALUES (?, ?, ?, 'active', CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP)""",
                        (user_id, plan_id, internal_payment_id, expires_at.isoformat())
                    )
                
                # 4. Обновляем статус в основной таблице users
                await set_subscription_status(user_id, True, expires_at)
                
                # Завершаем транзакцию
                await db.execute('COMMIT')
                
                logger.info(f"Payment confirmed and subscription activated for user {user_id}")
                return True
                
        except Exception as e:
            logger.exception(f"Error confirming payment: {e}")
            return False
    
    async def check_active_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Проверяет активную подписку пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"""SELECT s.id, s.plan_id, s.expires_at, s.activated_at, p.amount_kopecks
                    FROM {TABLE_SUBSCRIPTIONS} s
                    LEFT JOIN {TABLE_PAYMENTS} p ON s.payment_id = p.id
                    WHERE s.user_id = ? AND s.status = 'active' 
                    AND s.expires_at > ?
                    ORDER BY s.expires_at DESC
                    LIMIT 1""",
                (user_id, datetime.now(timezone.utc).isoformat())
            )
            row = await cursor.fetchone()
            
            if row:
                return {
                    'subscription_id': row[0],
                    'plan_id': row[1],
                    'expires_at': datetime.fromisoformat(row[2]),
                    'activated_at': datetime.fromisoformat(row[3]),
                    'amount_kopecks': row[4]
                }
            return None
    
    async def cancel_subscription(self, user_id: int) -> bool:
        """Отменяет активную подписку пользователя."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    f"""UPDATE {TABLE_SUBSCRIPTIONS}
                        SET status = 'cancelled',
                            cancelled_at = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND status = 'active'""",
                    (user_id,)
                )
                
                # Обновляем статус в основной таблице
                await set_subscription_status(user_id, False, None)
                
                await db.commit()
                logger.info(f"Subscription cancelled for user {user_id}")
                return True
                
        except Exception as e:
            logger.exception(f"Error cancelling subscription: {e}")
            return False
    
    async def get_user_payment_history(self, user_id: int) -> list:
        """Возвращает историю платежей пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"""SELECT order_id, plan_id, amount_kopecks, status, created_at, confirmed_at
                    FROM {TABLE_PAYMENTS}
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT 10""",
                (user_id,)
            )
            
            payments = []
            async for row in cursor:
                payments.append({
                    'order_id': row[0],
                    'plan_id': row[1],
                    'amount_kopecks': row[2],
                    'status': row[3],
                    'created_at': row[4],
                    'confirmed_at': row[5]
                })
            
            return payments
    
    async def grant_subscription(
        self,
        user_id: int,
        plan_id: str,
        days: Optional[int] = None,
        reason: str = "admin_grant"
    ) -> bool:
        """Выдает подписку пользователю вручную (для админов)."""
        try:
            from .config import get_subscription_end_date
            
            if days:
                expires_at = datetime.now(timezone.utc) + timedelta(days=days)
            else:
                expires_at = get_subscription_end_date(plan_id)
            
            async with aiosqlite.connect(self.db_path) as db:
                # Создаем фиктивный платеж
                cursor = await db.execute(
                    f"""INSERT INTO {TABLE_PAYMENTS}
                        (user_id, order_id, plan_id, amount_kopecks, status, metadata)
                        VALUES (?, ?, ?, 0, 'granted', ?)""",
                    (user_id, f"grant_{user_id}_{uuid.uuid4().hex[:8]}", plan_id, reason)
                )
                payment_id = cursor.lastrowid
                
                # Создаем подписку
                await db.execute(
                    f"""INSERT INTO {TABLE_SUBSCRIPTIONS}
                        (user_id, plan_id, payment_id, status, starts_at, expires_at, activated_at)
                        VALUES (?, ?, ?, 'active', CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP)""",
                    (user_id, plan_id, payment_id, expires_at.isoformat())
                )
                
                # Обновляем основную таблицу
                await set_subscription_status(user_id, True, expires_at)
                
                await db.commit()
                logger.info(f"Subscription granted to user {user_id} until {expires_at}")
                return True
                
        except Exception as e:
            logger.exception(f"Error granting subscription: {e}")
            return False