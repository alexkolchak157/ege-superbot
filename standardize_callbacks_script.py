#!/usr/bin/env python3
"""
Скрипт для стандартизации callback_data во всех модулях
"""

import re
import os
from pathlib import Path

# Словарь замен callback_data
CALLBACK_REPLACEMENTS = {
    # Task20
    't20_new_topic': 't20_new',
    
    # Task19
    't19_new_topic': 't19_new',
    
    # Task24
    'task24_progress': 't24_progress',
    'task24_menu': 't24_menu',
    'task24_practice': 't24_practice',
    
    # Task25
    't25_new_topic': 't25_new',
}

# Файлы для обработки
FILES_TO_PROCESS = [
    'task20/plugin.py',
    'task20/handlers.py',
    'task19/plugin.py', 
    'task19/handlers.py',
    'task24/plugin.py',
    'task24/handlers.py',
    'task25/plugin.py',
    'task25/handlers.py',
]

def replace_callbacks_in_file(filepath):
    """Заменяет callback_data в файле"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original = content
        
        # Заменяем callback_data в кнопках
        for old, new in CALLBACK_REPLACEMENTS.items():
            # Паттерн для callback_data в кнопках
            pattern1 = rf'callback_data="{re.escape(old)}"'
            replacement1 = f'callback_data="{new}"'
            content = re.sub(pattern1, replacement1, content)
            
            # Паттерн для pattern в обработчиках
            pattern2 = rf'pattern="\^{re.escape(old)}\$"'
            replacement2 = f'pattern="^{new}$"'
            content = re.sub(pattern2, replacement2, content)
            
            # Паттерн для проверок в коде
            pattern3 = rf'== "{re.escape(old)}"'
            replacement3 = f'== "{new}"'
            content = re.sub(pattern3, replacement3, content)
        
        # Сохраняем, если были изменения
        if content != original:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✅ Обновлен: {filepath}")
            return True
        else:
            print(f"⏭️  Без изменений: {filepath}")
            return False
    
    except FileNotFoundError:
        print(f"❌ Файл не найден: {filepath}")
        return False
    except Exception as e:
        print(f"❌ Ошибка при обработке {filepath}: {e}")
        return False

def main():
    """Основная функция"""
    print("🔧 Стандартизация callback_data...\n")
    
    updated_count = 0
    
    for filepath in FILES_TO_PROCESS:
        if replace_callbacks_in_file(filepath):
            updated_count += 1
    
    print(f"\n✨ Готово! Обновлено файлов: {updated_count}")
    
    # Дополнительные инструкции
    print("\n📝 Не забудьте также:")
    print("1. Проверить, что все обработчики зарегистрированы с новыми паттернами")
    print("2. Протестировать работу кнопок после изменений")
    print("3. Обновить документацию при необходимости")

if __name__ == "__main__":
    main()