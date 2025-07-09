#!/usr/bin/env python3
"""Скрипт для проверки состояния подписок в базе данных."""

import asyncio
import aiosqlite
from datetime import datetime
import sys
import os

# Добавляем путь к корневой директории
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.db import DATABASE_FILE


async def check_database():
    """Проверяет состояние базы данных подписок."""
    print(f"Проверка базы данных: {DATABASE_FILE}")
    print("=" * 50)
    
    async with aiosqlite.connect(DATABASE_FILE) as conn:
        # Проверяем таблицы
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%subscr%' OR name LIKE '%module%' OR name='payments'"
        )
        tables = await cursor.fetchall()
        
        print(f"\nНайдены таблицы:")
        for table in tables:
            print(f"  - {table[0]}")
            
            # Показываем структуру таблицы
            cursor = await conn.execute(f"PRAGMA table_info({table[0]})")
            columns = await cursor.fetchall()
            print(f"    Колонки: {', '.join([col[1] for col in columns])}")
            
            # Показываем количество записей
            cursor = await conn.execute(f"SELECT COUNT(*) FROM {table[0]}")
            count = await cursor.fetchone()
            print(f"    Записей: {count[0]}")
        
        # Проверяем активные подписки
        print(f"\n\nАктивные модульные подписки:")
        print("-" * 50)
        
        try:
            cursor = await conn.execute(
                """
                SELECT user_id, module_code, plan_id, expires_at 
                FROM module_subscriptions 
                WHERE is_active = 1 AND expires_at > ?
                ORDER BY user_id, module_code
                """,
                (datetime.now(),)
            )
            subscriptions = await cursor.fetchall()
            
            if subscriptions:
                current_user = None
                for sub in subscriptions:
                    if sub[0] != current_user:
                        current_user = sub[0]
                        print(f"\nПользователь {sub[0]}:")
                    print(f"  - {sub[1]} (план: {sub[2]}) до {sub[3]}")
            else:
                print("  Нет активных модульных подписок")
        except Exception as e:
            print(f"  Ошибка при чтении module_subscriptions: {e}")
        
        # Проверяем последние платежи
        print(f"\n\nПоследние 10 платежей:")
        print("-" * 50)
        
        try:
            cursor = await conn.execute(
                """
                SELECT user_id, order_id, plan_id, status, created_at 
                FROM payments 
                ORDER BY created_at DESC 
                LIMIT 10
                """
            )
            payments = await cursor.fetchall()
            
            if payments:
                for payment in payments:
                    print(f"User {payment[0]}: {payment[2]} - {payment[3]} ({payment[4]})")
            else:
                print("  Нет платежей")
        except Exception as e:
            print(f"  Ошибка при чтении payments: {e}")


if __name__ == "__main__":
    asyncio.run(check_database())