#!/usr/bin/env python3
"""
Диагностический скрипт для проверки состояния бота.
Помогает понять, что работает, а что нет.
"""

import os
import sys
import importlib
import traceback
from datetime import datetime

# Цвета для вывода
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def check_file_exists(file_path: str) -> bool:
    """Проверяет существование файла."""
    exists = os.path.exists(file_path)
    status = f"{Colors.GREEN}✓{Colors.RESET}" if exists else f"{Colors.RED}✗{Colors.RESET}"
    print(f"  {status} {file_path}")
    return exists


def check_module_import(module_name: str) -> bool:
    """Проверяет возможность импорта модуля."""
    try:
        importlib.import_module(module_name)
        print(f"  {Colors.GREEN}✓{Colors.RESET} {module_name}")
        return True
    except Exception as e:
        print(f"  {Colors.RED}✗{Colors.RESET} {module_name}: {str(e)[:50]}...")
        return False


def check_env_vars() -> dict:
    """Проверяет наличие необходимых переменных окружения."""
    required_vars = [
        'TELEGRAM_BOT_TOKEN',
        'YANDEX_GPT_API_KEY',
        'YANDEX_GPT_FOLDER_ID'
    ]
    
    optional_vars = [
        'BOT_ADMIN_IDS',
        'REQUIRED_CHANNEL',
        'DATABASE_FILE'
    ]
    
    results = {}
    
    print(f"\n{Colors.BOLD}Обязательные переменные:{Colors.RESET}")
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"  {Colors.GREEN}✓{Colors.RESET} {var} = {'*' * min(len(value), 10)}...")
            results[var] = True
        else:
            print(f"  {Colors.RED}✗{Colors.RESET} {var} не установлена")
            results[var] = False
    
    print(f"\n{Colors.BOLD}Опциональные переменные:{Colors.RESET}")
    for var in optional_vars:
        value = os.getenv(var)
        if value:
            print(f"  {Colors.GREEN}✓{Colors.RESET} {var} = {value[:20]}...")
        else:
            print(f"  {Colors.YELLOW}○{Colors.RESET} {var} не установлена")
    
    return results


def check_plugins() -> list:
    """Проверяет загрузку плагинов."""
    working_plugins = []
    
    try:
        from core.plugin_loader import discover_plugins, PLUGINS
        
        # Очищаем список для чистого теста
        PLUGINS.clear()
        
        # Загружаем плагины
        discover_plugins()
        
        if PLUGINS:
            for plugin in PLUGINS:
                print(f"  {Colors.GREEN}✓{Colors.RESET} {plugin.code} - {plugin.title}")
                working_plugins.append(plugin.code)
        else:
            print(f"  {Colors.RED}✗{Colors.RESET} Плагины не загружены")
            
    except Exception as e:
        print(f"  {Colors.RED}✗{Colors.RESET} Ошибка загрузки плагинов: {e}")
        
    return working_plugins


def check_handlers(plugin_code: str) -> dict:
    """Проверяет обработчики конкретного плагина."""
    results = {
        'imported': False,
        'functions': [],
        'errors': []
    }
    
    try:
        module = importlib.import_module(f"{plugin_code}.handlers")
        results['imported'] = True
        
        # Проверяем основные функции
        important_functions = [
            'entry_from_menu',
            'handle_answer',
            'cmd_start',
            'cmd_quiz'
        ]
        
        for func_name in dir(module):
            if func_name.startswith('_'):
                continue
                
            obj = getattr(module, func_name)
            if callable(obj):
                if func_name in important_functions:
                    print(f"    {Colors.GREEN}✓{Colors.RESET} {func_name}")
                results['functions'].append(func_name)
                
    except SyntaxError as e:
        results['errors'].append(f"SyntaxError: строка {e.lineno}")
        print(f"    {Colors.RED}✗ Синтаксическая ошибка: строка {e.lineno}{Colors.RESET}")
    except Exception as e:
        results['errors'].append(str(e))
        print(f"    {Colors.RED}✗ Ошибка импорта: {str(e)[:50]}...{Colors.RESET}")
    
    return results


def test_basic_bot_start():
    """Тестирует базовый запуск бота."""
    print(f"\n{Colors.BOLD}5. Тест базового запуска бота:{Colors.RESET}")
    
    try:
        from telegram.ext import Application
        from core.config import BOT_TOKEN
        
        if BOT_TOKEN:
            print(f"  {Colors.GREEN}✓{Colors.RESET} BOT_TOKEN загружен")
            print(f"  {Colors.BLUE}ℹ{Colors.RESET} Токен: {'*' * 10}...{BOT_TOKEN[-10:]}")
            
            # Пробуем создать приложение
            try:
                app = Application.builder().token(BOT_TOKEN).build()
                print(f"  {Colors.GREEN}✓{Colors.RESET} Application создан успешно")
                return True
            except Exception as e:
                print(f"  {Colors.RED}✗{Colors.RESET} Ошибка создания Application: {e}")
                return False
        else:
            print(f"  {Colors.RED}✗{Colors.RESET} BOT_TOKEN не найден")
            return False
            
    except Exception as e:
        print(f"  {Colors.RED}✗{Colors.RESET} Критическая ошибка: {e}")
        return False


def generate_report(results: dict):
    """Генерирует итоговый отчет."""
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}ИТОГОВЫЙ ОТЧЕТ{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
    
    # Подсчет результатов
    total_checks = 0
    passed_checks = 0
    
    for category, data in results.items():
        if isinstance(data, bool):
            total_checks += 1
            if data:
                passed_checks += 1
        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, bool):
                    total_checks += 1
                    if value:
                        passed_checks += 1
    
    percentage = (passed_checks / total_checks * 100) if total_checks > 0 else 0
    
    # Статус
    if percentage >= 80:
        status = f"{Colors.GREEN}ХОРОШО{Colors.RESET}"
        recommendation = "Бот готов к запуску с минимальными исправлениями"
    elif percentage >= 50:
        status = f"{Colors.YELLOW}ТРЕБУЕТ ВНИМАНИЯ{Colors.RESET}"
        recommendation = "Необходимо исправить критические ошибки перед запуском"
    else:
        status = f"{Colors.RED}КРИТИЧЕСКОЕ СОСТОЯНИЕ{Colors.RESET}"
        recommendation = "Требуется серьезное вмешательство или откат изменений"
    
    print(f"\nОбщий статус: {status}")
    print(f"Пройдено проверок: {passed_checks}/{total_checks} ({percentage:.1f}%)")
    print(f"\nРекомендация: {recommendation}")
    
    # Критические проблемы
    critical_issues = []
    
    if not results.get('env_vars', {}).get('TELEGRAM_BOT_TOKEN'):
        critical_issues.append("Не установлен TELEGRAM_BOT_TOKEN")
    
    if not results.get('core_modules', {}).get('core.app'):
        critical_issues.append("Не загружается основной модуль core.app")
    
    for plugin, data in results.get('plugins', {}).items():
        if data.get('errors'):
            critical_issues.append(f"Ошибки в плагине {plugin}: {data['errors'][0]}")
    
    if critical_issues:
        print(f"\n{Colors.RED}Критические проблемы:{Colors.RESET}")
        for i, issue in enumerate(critical_issues, 1):
            print(f"  {i}. {issue}")
    
    # Следующие шаги
    print(f"\n{Colors.BOLD}Следующие шаги:{Colors.RESET}")
    
    if critical_issues:
        print("1. Исправьте критические проблемы:")
        if 'SyntaxError' in str(critical_issues):
            print("   - Запустите: python fix_syntax_errors.py")
        if 'TELEGRAM_BOT_TOKEN' in str(critical_issues):
            print("   - Создайте файл .env с токеном бота")
            
        print("2. После исправления запустите диагностику снова")
    else:
        print("1. Запустите бота: python -m core.app")
        print("2. Проверьте основные функции")
        print("3. Постепенно добавляйте валидацию состояний")
    
    # Сохранение отчета
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = f"diagnostic_report_{timestamp}.txt"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"Диагностический отчет от {datetime.now()}\n")
        f.write(f"{'='*60}\n")
        f.write(f"Статус: {status}\n")
        f.write(f"Пройдено проверок: {passed_checks}/{total_checks}\n")
        f.write(f"\nДетали:\n{results}\n")
    
    print(f"\n📄 Отчет сохранен в: {report_file}")


def main():
    """Основная функция диагностики."""
    print(f"{Colors.BOLD}🔍 ДИАГНОСТИКА СОСТОЯНИЯ БОТА{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    results = {}
    
    # 1. Проверка файлов
    print(f"{Colors.BOLD}1. Проверка основных файлов:{Colors.RESET}")
    essential_files = [
        'core/app.py',
        'core/config.py',
        'core/state_validator.py',
        'core/error_handler.py',
        '.env'
    ]
    
    file_results = {}
    for file in essential_files:
        file_results[file] = check_file_exists(file)
    results['files'] = file_results
    
    # 2. Проверка переменных окружения
    print(f"\n{Colors.BOLD}2. Проверка переменных окружения:{Colors.RESET}")
    
    # Загрузка .env если есть
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print(f"  {Colors.GREEN}✓{Colors.RESET} .env файл загружен")
    except:
        print(f"  {Colors.YELLOW}○{Colors.RESET} dotenv не установлен или .env не найден")
    
    results['env_vars'] = check_env_vars()
    
    # 3. Проверка основных модулей
    print(f"\n{Colors.BOLD}3. Проверка основных модулей:{Colors.RESET}")
    core_modules = [
        'core.app',
        'core.plugin_loader',
        'core.state_validator',
        'core.error_handler',
        'core.db'
    ]
    
    module_results = {}
    for module in core_modules:
        module_results[module] = check_module_import(module)
    results['core_modules'] = module_results
    
    # 4. Проверка плагинов
    print(f"\n{Colors.BOLD}4. Проверка плагинов:{Colors.RESET}")
    working_plugins = check_plugins()
    
    # Детальная проверка каждого плагина
    plugin_results = {}
    for plugin_code in ['test_part', 'task19', 'task20', 'task24', 'task25']:
        print(f"\n  {Colors.BLUE}Плагин {plugin_code}:{Colors.RESET}")
        plugin_results[plugin_code] = check_handlers(plugin_code)
    
    results['plugins'] = plugin_results
    
    # 5. Тест базового запуска
    results['bot_start'] = test_basic_bot_start()
    
    # Генерация отчета
    generate_report(results)


if __name__ == "__main__":
    main()