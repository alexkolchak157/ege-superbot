#!/usr/bin/env python3
"""
Скрипт для автоматического исправления распространенных синтаксических ошибок
после неудачной миграции.
"""

import os
import re
from typing import List, Tuple

def fix_indentation(file_path: str, error_lines: List[int] = None):
    """
    Исправляет проблемы с отступами в файле.
    """
    print(f"\n🔧 Исправление отступов в {file_path}")
    
    if not os.path.exists(file_path):
        print(f"❌ Файл не найден: {file_path}")
        return
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    fixed_lines = []
    changes_made = 0
    
    for i, line in enumerate(lines, 1):
        # Заменяем табы на 4 пробела
        if '\t' in line:
            fixed_line = line.replace('\t', '    ')
            if fixed_line != line:
                changes_made += 1
                print(f"  Строка {i}: заменены табы на пробелы")
            fixed_lines.append(fixed_line)
        else:
            fixed_lines.append(line)
    
    # Проверяем конкретные строки с ошибками
    if error_lines:
        for line_num in error_lines:
            if 0 < line_num <= len(fixed_lines):
                line = fixed_lines[line_num - 1]
                # Проверяем, что отступ кратен 4
                indent_match = re.match(r'^(\s*)', line)
                if indent_match:
                    indent = indent_match.group(1)
                    indent_len = len(indent)
                    if indent_len % 4 != 0:
                        # Округляем до ближайшего кратного 4
                        new_indent_len = round(indent_len / 4) * 4
                        new_indent = ' ' * new_indent_len
                        fixed_lines[line_num - 1] = new_indent + line.lstrip()
                        changes_made += 1
                        print(f"  Строка {line_num}: исправлен отступ ({indent_len} -> {new_indent_len} пробелов)")
    
    if changes_made > 0:
        # Создаем резервную копию
        backup_path = file_path + '.indent_backup'
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print(f"  ✅ Создана резервная копия: {backup_path}")
        
        # Записываем исправленный файл
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(fixed_lines)
        print(f"  ✅ Исправлено изменений: {changes_made}")
    else:
        print(f"  ℹ️ Изменений не требуется")


def fix_decorator_syntax(file_path: str):
    """
    Исправляет синтаксис декораторов валидации.
    """
    print(f"\n🔧 Проверка синтаксиса декораторов в {file_path}")
    
    if not os.path.exists(file_path):
        print(f"❌ Файл не найден: {file_path}")
        return
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Паттерн для поиска неправильного порядка декораторов
    pattern = r'(@validate_state_transition[^\n]+)\n(\s*)(@safe_handler\(\))'
    
    matches = list(re.finditer(pattern, content))
    
    if matches:
        print(f"  ⚠️ Найдено {len(matches)} неправильных порядков декораторов")
        
        # Исправляем порядок (safe_handler должен быть первым)
        for match in reversed(matches):  # В обратном порядке чтобы не сбить индексы
            validation_decorator = match.group(1)
            indent = match.group(2)
            safe_decorator = match.group(3)
            
            # Правильный порядок
            correct_order = f"{safe_decorator}\n{indent}{validation_decorator}"
            
            content = content[:match.start()] + correct_order + content[match.end():]
        
        # Сохраняем исправленный файл
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  ✅ Исправлен порядок декораторов")
    else:
        print(f"  ✅ Декораторы в правильном порядке")


def add_missing_function(file_path: str, function_name: str, function_code: str):
    """
    Добавляет недостающую функцию в файл.
    """
    print(f"\n🔧 Добавление функции {function_name} в {file_path}")
    
    if not os.path.exists(file_path):
        print(f"❌ Файл не найден: {file_path}")
        return
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Проверяем, есть ли уже такая функция
    if f"def {function_name}" in content or f"async def {function_name}" in content:
        print(f"  ℹ️ Функция {function_name} уже существует")
        return
    
    # Находим место для вставки (после последней функции)
    last_function_match = None
    for match in re.finditer(r'\n(async def \w+|def \w+)[^\n]*:\n(?:(?:\s{4,}|\n).*\n)*', content):
        last_function_match = match
    
    if last_function_match:
        insert_pos = last_function_match.end()
        # Добавляем два переноса строки перед новой функцией
        content = content[:insert_pos] + "\n\n" + function_code + content[insert_pos:]
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  ✅ Функция {function_name} добавлена")
    else:
        print(f"  ❌ Не удалось найти место для вставки функции")


def main():
    """Основная функция исправления."""
    print("🚀 Скрипт исправления синтаксических ошибок\n")
    
    # Файлы с ошибками отступов
    indent_errors = [
        ('task19/handlers.py', [787]),
        ('task20/handlers.py', [939]),
        ('task24/handlers.py', [1375]),
        ('test_part/handlers.py', [689]),
    ]
    
    # Исправляем отступы
    for file_path, error_lines in indent_errors:
        fix_indentation(file_path, error_lines)
    
    # Проверяем порядок декораторов во всех handlers
    handler_files = [
        'test_part/handlers.py',
        'test_part/missing_handlers.py',
        'task19/handlers.py',
        'task20/handlers.py',
        'task24/handlers.py',
        'task25/handlers.py',
    ]
    
    for file_path in handler_files:
        fix_decorator_syntax(file_path)
    
    # Добавляем недостающую функцию show_theory в task25
    show_theory_code = '''@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def show_theory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ теории по заданию 25."""
    query = update.callback_query
    
    text = """📚 <b>Теория по заданию 25</b>

<b>Структура развернутого ответа:</b>

1️⃣ <b>Обоснование (К1 - 2 балла)</b>
• Теоретическое обоснование тезиса
• Опора на обществоведческие понятия
• Логическая связь с вопросом

2️⃣ <b>Ответ на вопрос (К2 - 1 балл)</b>
• Четкий и однозначный ответ
• Соответствие заданному вопросу

3️⃣ <b>Примеры (К3 - 3 балла)</b>
• Три развернутых примера
• Из разных сфер общественной жизни
• Конкретные, с деталями

<b>Типичные ошибки:</b>
❌ Отсутствие теоретического обоснования
❌ Примеры из одной сферы
❌ Абстрактные примеры без конкретики
❌ Несоответствие примеров тезису"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎯 Попробовать", callback_data="t25_practice"),
        InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE'''
    
    add_missing_function('task25/handlers.py', 'show_theory', show_theory_code)
    
    print("\n✨ Исправления завершены!")
    print("\n📋 Дальнейшие действия:")
    print("1. Попробуйте запустить бота: python -m core.app")
    print("2. Если есть новые ошибки, запишите их")
    print("3. При необходимости восстановите из резервных копий")
    
    # Проверка импортов
    print("\n🔍 Проверка критических импортов...")
    
    critical_imports = [
        "from core.state_validator import validate_state_transition, state_validator",
        "from telegram.ext import ConversationHandler"
    ]
    
    for file_path in handler_files:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            missing = []
            for imp in critical_imports:
                if imp not in content:
                    missing.append(imp)
            
            if missing:
                print(f"\n⚠️ {file_path} отсутствуют импорты:")
                for m in missing:
                    print(f"   {m}")


if __name__ == "__main__":
    main()