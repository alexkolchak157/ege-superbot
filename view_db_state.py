# view_db_state.py - Просмотр текущего состояния БД для отладки

import sqlite3
from datetime import datetime
from tabulate import tabulate

DB_PATH = "baza8.db"  # Ваш путь к БД

def show_recent_payments():
    """Показывает последние платежи."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n💳 ПОСЛЕДНИЕ ПЛАТЕЖИ:")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            order_id,
            user_id,
            plan_id,
            status,
            amount_kopecks / 100.0 as amount_rub,
            created_at,
            payment_id
        FROM payments 
        ORDER BY created_at DESC 
        LIMIT 10
    """)
    
    payments = cursor.fetchall()
    headers = ["Order ID", "User", "Plan", "Status", "Сумма ₽", "Создан", "Payment ID"]
    
    if payments:
        print(tabulate(payments, headers=headers, tablefmt="grid"))
    else:
        print("Нет платежей")
    
    conn.close()

def show_active_subscriptions():
    """Показывает активные подписки."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n📱 АКТИВНЫЕ ПОДПИСКИ (module_subscriptions):")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            user_id,
            module_code,
            plan_id,
            expires_at,
            is_trial,
            payment_id
        FROM module_subscriptions 
        WHERE is_active = 1
        ORDER BY user_id, module_code
        LIMIT 20
    """)
    
    subs = cursor.fetchall()
    headers = ["User", "Module", "Plan", "Expires", "Trial", "Payment ID"]
    
    if subs:
        print(tabulate(subs, headers=headers, tablefmt="grid"))
    else:
        print("Нет активных модульных подписок")
    
    print("\n📱 АКТИВНЫЕ ПОДПИСКИ (user_subscriptions):")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            user_id,
            plan_id,
            status,
            expires_at,
            payment_id
        FROM user_subscriptions 
        WHERE status = 'active'
        ORDER BY user_id
        LIMIT 20
    """)
    
    subs = cursor.fetchall()
    headers = ["User", "Plan", "Status", "Expires", "Payment ID"]
    
    if subs:
        print(tabulate(subs, headers=headers, tablefmt="grid"))
    else:
        print("Нет активных подписок в user_subscriptions")
    
    conn.close()

def show_webhook_logs():
    """Показывает последние webhook логи."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n📝 ПОСЛЕДНИЕ WEBHOOK ЛОГИ:")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            order_id,
            status,
            payment_id,
            created_at
        FROM webhook_logs 
        ORDER BY created_at DESC 
        LIMIT 15
    """)
    
    logs = cursor.fetchall()
    headers = ["Order ID", "Status", "Payment ID", "Time"]
    
    if logs:
        print(tabulate(logs, headers=headers, tablefmt="grid"))
    else:
        print("Нет webhook логов")
    
    # Статистика по статусам
    cursor.execute("""
        SELECT status, COUNT(*) as count
        FROM webhook_logs
        GROUP BY status
        ORDER BY count DESC
    """)
    
    stats = cursor.fetchall()
    if stats:
        print("\n📊 Статистика по статусам:")
        print(tabulate(stats, headers=["Status", "Count"], tablefmt="simple"))
    
    conn.close()

def show_users_with_subscriptions():
    """Показывает пользователей с подписками."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n👥 ПОЛЬЗОВАТЕЛИ С ПОДПИСКАМИ:")
    print("=" * 80)
    
    cursor.execute("""
        SELECT DISTINCT 
            u.user_id,
            u.subscription_plan,
            u.is_subscribed,
            COUNT(DISTINCT ms.module_code) as active_modules,
            COUNT(DISTINCT us.plan_id) as active_plans
        FROM users u
        LEFT JOIN module_subscriptions ms ON u.user_id = ms.user_id AND ms.is_active = 1
        LEFT JOIN user_subscriptions us ON u.user_id = us.user_id AND us.status = 'active'
        GROUP BY u.user_id
        HAVING active_modules > 0 OR active_plans > 0
        ORDER BY u.user_id
    """)
    
    users = cursor.fetchall()
    headers = ["User ID", "Plan", "Subscribed", "Active Modules", "Active Plans"]
    
    if users:
        print(tabulate(users, headers=headers, tablefmt="grid"))
    else:
        print("Нет пользователей с активными подписками")
    
    conn.close()

def check_test_data():
    """Проверяет тестовые данные."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n🧪 ТЕСТОВЫЕ ДАННЫЕ:")
    print("=" * 80)
    
    # Тестовые платежи
    cursor.execute("""
        SELECT COUNT(*) FROM payments WHERE order_id LIKE 'test-%'
    """)
    test_payments = cursor.fetchone()[0]
    print(f"Тестовых платежей: {test_payments}")
    
    # Тестовые пользователи
    test_users = [123456, 789, 999]
    for user_id in test_users:
        cursor.execute("""
            SELECT COUNT(*) FROM module_subscriptions 
            WHERE user_id = ? AND is_active = 1
        """, (user_id,))
        modules = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM payments WHERE user_id = ?
        """, (user_id,))
        payments = cursor.fetchone()[0]
        
        print(f"User {user_id}: {modules} активных модулей, {payments} платежей")
    
    conn.close()

def main():
    print("🔍 СОСТОЯНИЕ БАЗЫ ДАННЫХ")
    print("=" * 80)
    print(f"БД: {DB_PATH}")
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    show_recent_payments()
    show_active_subscriptions()
    show_webhook_logs()
    show_users_with_subscriptions()
    check_test_data()
    
    print("\n✅ Готово!")

if __name__ == "__main__":
    main()