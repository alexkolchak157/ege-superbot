#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы плагина task19
"""

import asyncio
import logging
import sys
import os
import pytest

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

@pytest.mark.asyncio
async def test_task19():
    """Тестирование компонентов task19"""
    
    print("🧪 Тестирование task19...\n")
    
    # Тест 1: Проверка импорта плагина
    print("1️⃣ Проверка импорта плагина...")
    try:
        from task19.plugin import plugin
        print(f"✅ Плагин импортирован: {plugin.title} (приоритет: {plugin.menu_priority})")
    except Exception as e:
        print(f"❌ Ошибка импорта плагина: {e}")
        return
    
    # Тест 2: Проверка загрузки данных
    print("\n2️⃣ Проверка загрузки данных...")
    try:
        from task19 import handlers
        await handlers.init_task19_data()
        topics_count = len(handlers.task19_data.get('topics', []))
        print(f"✅ Загружено тем: {topics_count}")
        
        # Показываем список тем
        for topic in handlers.task19_data.get('topics', []):
            print(f"   - {topic['title']}")
    except Exception as e:
        print(f"❌ Ошибка загрузки данных: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Тест 3: Проверка AI evaluator
    print("\n3️⃣ Проверка AI evaluator...")
    try:
        from task19.evaluator import Task19AIEvaluator
        evaluator = Task19AIEvaluator()
        print(f"✅ AI evaluator создан")
        print(f"   Макс. баллов: {evaluator.requirements.max_score}")
        print(f"   Название: {evaluator.requirements.task_name}")
    except Exception as e:
        print(f"❌ Ошибка создания evaluator: {e}")
        return
    
    # Тест 4: Проверка системного промпта
    print("\n4️⃣ Проверка системного промпта...")
    try:
        prompt = evaluator.get_system_prompt()
        print(f"✅ Системный промпт получен ({len(prompt)} символов)")
        print(f"   Начало: {prompt[:100]}...")
    except Exception as e:
        print(f"❌ Ошибка получения промпта: {e}")
    
    # Тест 5: Проверка загрузки всех модулей
    print("\n5️⃣ Проверка всех плагинов...")
    try:
        from core.plugin_loader import discover_plugins, PLUGINS
        discover_plugins()
        print(f"✅ Загружено плагинов: {len(PLUGINS)}")
        for p in PLUGINS:
            print(f"   - {p.title} (код: {p.code}, приоритет: {p.menu_priority})")
    except Exception as e:
        print(f"❌ Ошибка загрузки плагинов: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n✨ Тестирование завершено!")

if __name__ == "__main__":
    asyncio.run(test_task19())
