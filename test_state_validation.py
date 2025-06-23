#!/usr/bin/env python3
"""
Тест валидации состояний после интеграции.
"""

import asyncio
import sys
import os
from unittest.mock import Mock, AsyncMock

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_state_validation():
    """Тестирование валидации состояний."""
    
    print("🧪 Тестирование валидации состояний...\n")
    
    # Тест 1: Импорт валидатора
    print("1️⃣ Проверка импорта валидатора...")
    try:
        from core.state_validator import state_validator, validate_state_transition
        print("✅ Валидатор импортирован успешно")
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        return
    
    # Тест 2: Проверка разрешенных переходов
    print("\n2️⃣ Проверка разрешенных переходов...")
    from core import states
    from telegram.ext import ConversationHandler
    
    # Тестируем валидные переходы
    valid_transitions = [
        (ConversationHandler.END, states.CHOOSING_MODE),
        (states.CHOOSING_MODE, states.CHOOSING_BLOCK),
        (states.CHOOSING_BLOCK, states.CHOOSING_TOPIC),
        (states.CHOOSING_TOPIC, states.ANSWERING),
        (states.ANSWERING, states.CHOOSING_NEXT_ACTION),
    ]
    
    for from_state, to_state in valid_transitions:
        is_valid = state_validator.is_valid_transition(123, from_state, to_state)
        status = "✅" if is_valid else "❌"
        print(f"{status} {state_validator._state_name(from_state)} → {state_validator._state_name(to_state)}")
    
    # Тест 3: Проверка недопустимых переходов
    print("\n3️⃣ Проверка недопустимых переходов...")
    invalid_transitions = [
        (states.ANSWERING, states.CHOOSING_BLOCK),
        (states.REVIEWING_MISTAKES, states.CHOOSING_EXAM_NUMBER),
    ]
    
    for from_state, to_state in invalid_transitions:
        is_valid = state_validator.is_valid_transition(123, from_state, to_state)
        status = "❌" if not is_valid else "✅ (неожиданно!)"
        print(f"{status} {state_validator._state_name(from_state)} → {state_validator._state_name(to_state)}")
    
    # Тест 4: Проверка декоратора
    print("\n4️⃣ Проверка работы декоратора...")
    
    @validate_state_transition({states.CHOOSING_MODE})
    async def test_handler(update, context):
        return states.ANSWERING
    
    # Мокаем Update и Context
    update = Mock()
    update.effective_user = Mock(id=456)
    context = Mock()
    
    # Устанавливаем состояние пользователя
    state_validator.set_state(456, states.CHOOSING_MODE)
    
    # Вызываем обработчик
    try:
        result = await test_handler(update, context)
        print("✅ Декоратор работает корректно")
        print(f"   Результат: переход в {state_validator._state_name(result)}")
    except Exception as e:
        print(f"❌ Ошибка в декораторе: {e}")
    
    # Тест 5: Статистика
    print("\n5️⃣ Проверка статистики...")
    stats = state_validator.get_stats()
    print(f"✅ Статистика доступна:")
    print(f"   Всего переходов: {stats['total_transitions']}")
    print(f"   Уникальных переходов: {stats['unique_transitions']}")
    print(f"   Активных пользователей: {stats['active_users']}")
    
    # Тест 6: Проверка интеграции с обработчиками
    print("\n6️⃣ Проверка интеграции с модулями...")
    
    modules_to_check = [
        'test_part.handlers',
        'task19.handlers', 
        'task20.handlers',
        'task25.handlers'
    ]
    
    for module_name in modules_to_check:
        try:
            module = __import__(module_name, fromlist=[''])
            
            # Проверяем, есть ли декорированные функции
            decorated_count = 0
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if callable(attr) and hasattr(attr, '__wrapped__'):
                    # Проверяем наличие валидации в цепочке декораторов
                    func = attr
                    while hasattr(func, '__wrapped__'):
                        if hasattr(func, '__name__') and 'validate_state_transition' in str(func):
                            decorated_count += 1
                            break
                        func = func.__wrapped__
            
            status = "✅" if decorated_count > 0 else "⚠️"
            print(f"{status} {module_name}: {decorated_count} обработчиков с валидацией")
            
        except ImportError as e:
            print(f"⚠️ {module_name}: не удалось импортировать ({e})")
    
    print("\n✨ Тестирование завершено!")


async def test_specific_handler():
    """Тест конкретного обработчика с валидацией."""
    print("\n🔍 Тест конкретного обработчика...")
    
    try:
        from test_part.handlers import entry_from_menu
        from telegram import Update, CallbackQuery, Message, Chat, User
        from telegram.ext import ContextTypes
        
        # Создаем мок Update
        update = Mock(spec=Update)
        update.effective_user = Mock(spec=User, id=789)
        update.callback_query = Mock(spec=CallbackQuery)
        update.callback_query.from_user = Mock(spec=User, id=789)
        update.callback_query.message = Mock(spec=Message)
        update.callback_query.message.chat = Mock(spec=Chat)
        update.callback_query.edit_message_text = AsyncMock()
        
        # Создаем мок Context
        context = Mock()
        context.bot = Mock()
        context.user_data = {}
        
        # Вызываем обработчик
        result = await entry_from_menu(update, context)
        
        print(f"✅ Обработчик entry_from_menu вернул: {result}")
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании обработчика: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_state_validation())
    asyncio.run(test_specific_handler())