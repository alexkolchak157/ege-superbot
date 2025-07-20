# find_real_error.py - Находим настоящую причину 502

import sys
import os
import traceback
import asyncio

print("🔍 ПОИСК РЕАЛЬНОЙ ОШИБКИ WEBHOOK")
print("=" * 60)

# Проверяем конфигурацию
print("\n1️⃣ Проверка конфигурации...")
try:
    from payment.config import DATABASE_PATH, TINKOFF_TERMINAL_KEY, TINKOFF_SECRET_KEY
    print(f"✅ DATABASE_PATH: {DATABASE_PATH}")
    print(f"✅ TINKOFF_TERMINAL_KEY: {'Установлен' if TINKOFF_TERMINAL_KEY else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"✅ TINKOFF_SECRET_KEY: {'Установлен' if TINKOFF_SECRET_KEY else '❌ НЕ УСТАНОВЛЕН'}")
    
    # Проверяем файл БД
    if os.path.exists(DATABASE_PATH):
        print(f"✅ Файл БД существует: {os.path.getsize(DATABASE_PATH):,} байт")
    else:
        print(f"❌ Файл БД НЕ НАЙДЕН: {DATABASE_PATH}")
        
except Exception as e:
    print(f"❌ Ошибка конфигурации: {e}")

# Симулируем вызов webhook с отладкой
print("\n2️⃣ Симуляция вызова webhook...")

class FakeRequest:
    async def json(self):
        return {
            "TerminalKey": "TEST",
            "OrderId": "test-order",
            "Status": "CONFIRMED", 
            "Token": "test",
            "PaymentId": "123",
            "Amount": 100000
        }
    
    class app:
        @staticmethod
        def get(key):
            return None

async def test_webhook_detailed():
    try:
        # Импортируем webhook
        print("\n🔍 Импорт webhook модуля...")
        from payment import webhook
        print("✅ Модуль импортирован")
        
        # Проверяем функции
        if hasattr(webhook, 'handle_webhook'):
            print("✅ handle_webhook найден")
        else:
            print("❌ handle_webhook НЕ найден")
            return
            
        # Проверяем verify_tinkoff_signature
        if hasattr(webhook, 'verify_tinkoff_signature'):
            print("✅ verify_tinkoff_signature найден")
            
            # Тестируем проверку подписи
            test_data = {"test": "data"}
            try:
                result = webhook.verify_tinkoff_signature(
                    test_data, "token", "terminal", "secret"
                )
                print(f"   Проверка подписи работает: {result}")
            except Exception as e:
                print(f"   ❌ Ошибка в verify_tinkoff_signature: {e}")
        
        # Создаем фейковый request
        fake_request = FakeRequest()
        fake_request.app = FakeRequest.app
        
        print("\n🔍 Вызов handle_webhook...")
        
        # Временно патчим функции для отладки
        original_verify = None
        if hasattr(webhook, 'verify_tinkoff_signature'):
            original_verify = webhook.verify_tinkoff_signature
            # Заменяем на функцию, которая всегда возвращает False
            webhook.verify_tinkoff_signature = lambda *args, **kwargs: False
            print("   Временно отключена проверка подписи")
        
        try:
            response = await webhook.handle_webhook(fake_request)
            print(f"✅ Webhook вернул: HTTP {response.status}")
            print(f"   Текст: {response.text}")
            
            if response.status == 502:
                print("\n❌ ВСЕ ЕЩЕ 502!")
        except Exception as e:
            print(f"\n❌ ОШИБКА В handle_webhook:")
            print(f"Тип: {type(e).__name__}")
            print(f"Сообщение: {e}")
            print("\nПолный traceback:")
            traceback.print_exc()
            
            # Детальный анализ
            error_str = str(e).lower()
            if "subscriptionmanager" in error_str:
                print("\n💡 Проблема с SubscriptionManager")
                print("Проверьте payment/subscription_manager.py")
            elif "no such table" in error_str:
                print("\n💡 Проблема с таблицей в БД")
                print(f"Ошибка: {e}")
            elif "getenv" in error_str:
                print("\n💡 Проблема с переменными окружения")
                print("Проверьте os.getenv() вызовы")
                
        finally:
            # Восстанавливаем оригинальную функцию
            if original_verify:
                webhook.verify_tinkoff_signature = original_verify
                
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА:")
        traceback.print_exc()

# Проверяем SubscriptionManager отдельно
print("\n3️⃣ Проверка SubscriptionManager...")
try:
    from payment.subscription_manager import SubscriptionManager
    print("✅ SubscriptionManager импортирован")
    
    # Пробуем создать экземпляр
    sm = SubscriptionManager()
    print("✅ Экземпляр создан")
    
    # Проверяем методы
    methods = ['activate_subscription', 'update_payment_status', 'get_payment_by_order_id']
    for method in methods:
        if hasattr(sm, method):
            print(f"✅ Метод {method} существует")
        else:
            print(f"❌ Метод {method} НЕ НАЙДЕН")
            
except Exception as e:
    print(f"❌ Ошибка SubscriptionManager: {e}")
    traceback.print_exc()

# Запускаем тест
print("\n" + "=" * 60)
asyncio.run(test_webhook_detailed())

print("\n💡 СЛЕДУЮЩИЕ ШАГИ:")
print("1. Если видите конкретную ошибку выше - исправьте её")
print("2. Перезапустите бота")
print("3. Запустите тест снова")