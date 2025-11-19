#!/usr/bin/env python3
"""
Скрипт для исправления подписки пользователя 1216829039.

ПРОБЛЕМА:
Пользователь оплатил подписку 24.10.2025, получил доступ вовремя.
Но 19.11.2025 активировался старый webhook, который перезаписал дату окончания.

Должна истечь: 24.11.2025 (вчера)
Фактически:    19.12.2025 (через месяц)

РЕШЕНИЕ:
Установить правильную дату окончания: 24.11.2025
"""
import asyncio
import aiosqlite
from datetime import datetime, timezone

USER_ID = 1216829039
CORRECT_EXPIRES_DATE = '2025-11-24T07:53:22+00:00'  # 24.10 + 30 дней
PAYMENT_DATE = '2025-10-24T07:53:22'  # Дата создания платежа

async def fix_subscription():
    """Исправляет подписку пользователя."""
    try:
        async with aiosqlite.connect('quiz_async.db') as db:
            print("=" * 80)
            print(f"ИСПРАВЛЕНИЕ ПОДПИСКИ ПОЛЬЗОВАТЕЛЯ {USER_ID}")
            print("=" * 80)
            print()

            # Получаем текущие подписки
            cursor = await db.execute("""
                SELECT module_code, plan_id, created_at, expires_at, is_active
                FROM module_subscriptions
                WHERE user_id = ?
            """, (USER_ID,))
            subscriptions = await cursor.fetchall()

            if not subscriptions:
                print("❌ Подписок не найдено")
                return

            print("📦 ТЕКУЩИЕ ПОДПИСКИ:")
            for module_code, plan_id, created_at, expires_at, is_active in subscriptions:
                print(f"   - {module_code}: {plan_id}")
                print(f"     Создана: {created_at}")
                print(f"     Истекает: {expires_at}")

            print()
            print("🔧 ИСПРАВЛЕНИЕ:")
            print()
            print(f"   Правильная дата создания: {PAYMENT_DATE}")
            print(f"   Правильная дата окончания: {CORRECT_EXPIRES_DATE}")
            print(f"   Длительность: 30 дней")
            print()

            # Обновляем все подписки
            updated_count = 0
            for module_code, plan_id, created_at, expires_at, is_active in subscriptions:
                await db.execute("""
                    UPDATE module_subscriptions
                    SET created_at = ?,
                        expires_at = ?,
                        is_active = 0
                    WHERE user_id = ? AND module_code = ?
                """, (PAYMENT_DATE, CORRECT_EXPIRES_DATE, USER_ID, module_code))

                print(f"   ✅ Обновлен модуль {module_code}")
                print(f"      Было: created={created_at}, expires={expires_at}")
                print(f"      Стало: created={PAYMENT_DATE}, expires={CORRECT_EXPIRES_DATE}")
                print(f"      Статус: is_active=0 (подписка истекла 24.11)")
                print()

                updated_count += 1

            await db.commit()

            print("=" * 80)
            print(f"✅ ИСПРАВЛЕНИЕ ЗАВЕРШЕНО")
            print(f"   Обновлено модулей: {updated_count}")
            print(f"   Подписка истекла: 24.11.2025 (вчера)")
            print(f"   Статус: неактивна")
            print("=" * 80)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return

if __name__ == '__main__':
    print()
    print("⚠️  ВНИМАНИЕ: Этот скрипт исправит подписку пользователя 1216829039")
    print("   Установит правильную дату окончания: 24.11.2025 (истекла)")
    print()
    response = input("Продолжить? (yes/no): ")

    if response.lower() in ['yes', 'y', 'да']:
        asyncio.run(fix_subscription())
        print()
        print("🔍 Проверить результат:")
        print(f"   python3 check_user_subscription.py {USER_ID}")
    else:
        print("Отменено")
