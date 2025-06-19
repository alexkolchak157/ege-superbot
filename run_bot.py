# run_bot.py - файл в корне проекта (рядом с папками core, test_part, task24)

"""
Утилита для загрузки переменных окружения из .env файла
Добавьте в начало вашего главного скрипта бота:

from load_env import load_env
load_env()
"""

import os
from pathlib import Path

def load_env(env_file='.env'):
    """
    Загружает переменные окружения из .env файла.
    
    Args:
        env_file: Путь к .env файлу
    """
    env_path = Path(env_file)
    
    if not env_path.exists():
        print(f"⚠️ Файл {env_file} не найден!")
        print("Создайте его на основе .env.template")
        return False
    
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # Пропускаем пустые строки и комментарии
            if not line or line.startswith('#'):
                continue
            
            # Разделяем на ключ и значение
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Убираем кавычки если есть
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                
                # Устанавливаем переменную окружения
                os.environ[key] = value
                print(f"✅ Загружено: {key}")
    
    # Проверяем обязательные переменные
    required_vars = [
        'TELEGRAM_BOT_TOKEN',
        'YANDEX_GPT_API_KEY',
        'YANDEX_GPT_FOLDER_ID'
    ]
    
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        print(f"\n⚠️ Отсутствуют обязательные переменные: {', '.join(missing)}")
        print("AI-проверка будет недоступна!")
        return False
    
    print("\n✅ Все переменные окружения загружены успешно!")
    return True


if __name__ == "__main__":
    # Тест загрузки
    if load_env():
        print("\nТекущие значения:")
        print(f"TELEGRAM_BOT_TOKEN: {'*' * 10}{os.getenv('TELEGRAM_BOT_TOKEN', '')[-10:]}")
        print(f"YANDEX_GPT_API_KEY: {'*' * 10}{os.getenv('YANDEX_GPT_API_KEY', '')[-10:]}")
        print(f"YANDEX_GPT_FOLDER_ID: {os.getenv('YANDEX_GPT_FOLDER_ID', 'не установлен')}")
        
if __name__ == "__main__":
    from core.app import main
    main()
