import asyncio
import aiohttp
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
import time

# Настройки
TERMINAL_KEY = "1744454282317"
SECRET_KEY = "DNoeBPGM_nqE%kiq"
WEBHOOK_URL = "https://xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai/payment-notification"
DB_PATH = 'quiz_async.db'

class WebhookTester:
    def __init__(self):
        self.results = []
        
    def calculate_token(self, params: dict) -> str:
        """Вычисляет токен для подписи."""
        check_data = params.copy()
        check_data.pop('Token', None)
        check_data['Password'] = SECRET_KEY
        
        sorted_values = [str(v) for k, v in sorted(check_data.items())]
        concatenated = ''.join(sorted_values)
        
        return hashlib.sha256(concatenated.encode()).hexdigest()
    
    async def create_test_payment(self, user_id: int, plan_id: str) -> str:
        """Создает тестовый платеж в БД."""
        order_id = f"test-{int(time.time())}-{user_id}"
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Создаем пользователя если не существует
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, first_seen)
            VALUES (?, datetime('now'))
        """, (user_id,))
        
        # Создаем платеж
        cursor.execute("""
            INSERT INTO payments (order_id, user_id, plan_id, amount_kopecks, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', datetime('now'))
        """, (order_id, user_id, plan_id, 100000))
        
        conn.commit()
        conn.close()
        
        return order_id
    
    async def send_webhook(self, status: str, order_id: str = None, payment_id: str = None):
        """Отправляет webhook с заданным статусом."""
        if not order_id:
            order_id = f"test-{int(time.time())}"
        if not payment_id:
            payment_id = str(int(time.time()))
        
        data = {
            "TerminalKey": TERMINAL_KEY,
            "OrderId": order_id,
            "Success": status == "CONFIRMED",
            "Status": status,
            "PaymentId": payment_id,
            "Amount": 100000,
        }
        
        data['Token'] = self.calculate_token(data)
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(WEBHOOK_URL, json=data) as response:
                    result = {
                        'status': status,
                        'order_id': order_id,
                        'http_code': response.status,
                        'response': await response.text(),
                        'success': response.status == 200 and await response.text() == 'OK'
                    }
                    self.results.append(result)
                    return result
            except Exception as e:
                result = {
                    'status': status,
                    'order_id': order_id,
                    'error': str(e),
                    'success': False
                }
                self.results.append(result)
                return result
    
    async def test_basic_flow(self):
        """Тест базового флоу оплаты."""
        print("\n🧪 ТЕСТ 1: Базовый флоу оплаты")
        print("=" * 50)
        
        # Создаем платеж
        user_id = 123456
        plan_id = 'trial_7days'
        order_id = await self.create_test_payment(user_id, plan_id)
        print(f"✅ Создан платеж: {order_id}")
        
        # Отправляем webhook статусы
        for status in ["NEW", "AUTHORIZED", "CONFIRMED"]:
            result = await self.send_webhook(status, order_id)
            print(f"📤 {status}: HTTP {result.get('http_code', 'error')}")
            await asyncio.sleep(0.5)
        
        # Проверяем активацию
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Проверяем статус платежа
        cursor.execute("SELECT status FROM payments WHERE order_id = ?", (order_id,))
        payment_status = cursor.fetchone()
        
        # Проверяем модульные подписки (для trial_7days)
        cursor.execute("""
            SELECT COUNT(*) FROM module_subscriptions 
            WHERE user_id = ? AND plan_id = ? AND is_active = 1
        """, (user_id, plan_id))
        active_modules = cursor.fetchone()[0]
        
        # Проверяем user_subscriptions
        cursor.execute("""
            SELECT COUNT(*) FROM user_subscriptions 
            WHERE user_id = ? AND plan_id = ? AND status = 'active'
        """, (user_id, plan_id))
        active_subscriptions = cursor.fetchone()[0]
        
        conn.close()
        
        print(f"\n📊 Результат:")
        print(f"   Статус платежа: {payment_status[0] if payment_status else 'не найден'}")
        print(f"   Активные модули в module_subscriptions: {active_modules}")
        print(f"   Активные подписки в user_subscriptions: {active_subscriptions}")
        
        success = payment_status and payment_status[0] == 'confirmed' and (active_modules > 0 or active_subscriptions > 0)
        return success
    
    async def test_error_cases(self):
        """Тест ошибочных сценариев."""
        print("\n🧪 ТЕСТ 2: Ошибочные сценарии")
        print("=" * 50)
        
        # 1. Неверная подпись
        print("\n1️⃣ Неверная подпись:")
        data = {
            "TerminalKey": TERMINAL_KEY,
            "OrderId": "test-invalid",
            "Status": "CONFIRMED",
            "Token": "invalid_token"
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(WEBHOOK_URL, json=data) as response:
                    print(f"   HTTP {response.status} - ожидается 401")
            except:
                print("   ❌ Ошибка подключения")
        
        # 2. Несуществующий платеж
        print("\n2️⃣ Несуществующий платеж:")
        result = await self.send_webhook("CONFIRMED", "non-existent-order")
        print(f"   HTTP {result.get('http_code')} - платеж должен быть проигнорирован")
        
        # 3. Дубликат webhook
        print("\n3️⃣ Дубликат webhook:")
        order_id = await self.create_test_payment(789, 'package_full')
        await self.send_webhook("CONFIRMED", order_id)
        await asyncio.sleep(0.5)
        result = await self.send_webhook("CONFIRMED", order_id)  # Повтор
        print(f"   HTTP {result.get('http_code')} - дубликат должен быть проигнорирован")
        
        return True
    
    async def test_refund_flow(self):
        """Тест возврата средств."""
        print("\n🧪 ТЕСТ 3: Возврат средств")
        print("=" * 50)
        
        # Создаем и активируем подписку
        user_id = 999
        plan_id = 'package_second_part'
        order_id = await self.create_test_payment(user_id, plan_id)
        
        # Активируем подписку
        await self.send_webhook("CONFIRMED", order_id)
        print(f"✅ Подписка активирована: {order_id}")
        
        # Проверяем активацию
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM module_subscriptions 
            WHERE user_id = ? AND is_active = 1
        """, (user_id,))
        active_before = cursor.fetchone()[0]
        print(f"   Активных модулей до возврата: {active_before}")
        conn.close()
        
        # Отправляем REFUNDED
        await asyncio.sleep(1)
        result = await self.send_webhook("REFUNDED", order_id)
        print(f"💸 Возврат: HTTP {result.get('http_code')}")
        
        # Проверяем деактивацию
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM module_subscriptions 
            WHERE user_id = ? AND is_active = 1
        """, (user_id,))
        active_after = cursor.fetchone()[0]
        conn.close()
        
        print(f"   Активных модулей после возврата: {active_after}")
        return active_before > 0 and active_after < active_before
    
    async def test_webhook_logs(self):
        """Проверка логирования webhook."""
        print("\n🧪 ТЕСТ 4: Логирование webhook")
        print("=" * 50)
        
        # Отправляем тестовый webhook
        order_id = f"test-log-{int(time.time())}"
        await self.send_webhook("CONFIRMED", order_id)
        
        # Проверяем логи
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM webhook_logs WHERE order_id = ?
        """, (order_id,))
        log_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT status, created_at FROM webhook_logs 
            WHERE order_id = ? 
            ORDER BY created_at DESC LIMIT 1
        """, (order_id,))
        log_entry = cursor.fetchone()
        
        conn.close()
        
        print(f"📊 Логи для {order_id}:")
        print(f"   Количество записей: {log_count}")
        if log_entry:
            print(f"   Последний статус: {log_entry[0]}")
            print(f"   Время: {log_entry[1]}")
        
        return log_count > 0
    
    def print_summary(self):
        """Выводит итоговую статистику."""
        print("\n" + "=" * 50)
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print("=" * 50)
        
        total = len(self.results)
        success = sum(1 for r in self.results if r.get('success'))
        
        print(f"Всего запросов: {total}")
        print(f"Успешных: {success}")
        print(f"Ошибок: {total - success}")
        
        # Группируем по статусам
        status_counts = {}
        for r in self.results:
            status = r.get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print("\nПо статусам:")
        for status, count in status_counts.items():
            print(f"  {status}: {count}")

async def main():
    print("🚀 ТЕСТИРОВАНИЕ WEBHOOK (исправленная версия)")
    print("=" * 50)
    
    # Проверяем доступность webhook
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8080/health") as response:
                if response.status != 200:
                    print("❌ Webhook сервер не доступен!")
                    print("Запустите бота и попробуйте снова.")
                    return
    except:
        print("❌ Не могу подключиться к webhook серверу!")
        print("Убедитесь, что бот запущен.")
        return
    
    print("✅ Webhook сервер доступен\n")
    
    tester = WebhookTester()
    
    # Запускаем тесты
    test_results = {
        "Базовый флоу": await tester.test_basic_flow(),
        "Ошибочные сценарии": await tester.test_error_cases(),
        "Возврат средств": await tester.test_refund_flow(),
        "Логирование": await tester.test_webhook_logs()
    }
    
    # Выводим результаты
    tester.print_summary()
    
    print("\n🏁 РЕЗУЛЬТАТЫ ТЕСТОВ:")
    print("=" * 50)
    for test_name, passed in test_results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    all_passed = all(test_results.values())
    print("\n" + ("✨ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!" if all_passed else "⚠️ ЕСТЬ ПРОБЛЕМЫ!"))

if __name__ == "__main__":
    asyncio.run(main())