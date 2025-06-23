#!/usr/bin/env python3
"""
Скрипт для автоматического добавления валидации состояний в обработчики.
Создает резервные копии и обновляет файлы handlers.py
"""

import os
import re
import shutil
from datetime import datetime
from typing import List, Tuple, Dict

# Паттерны для поиска обработчиков
HANDLER_PATTERN = r'(@safe_handler\(\))\s*\n\s*(async def (\w+)\(update: Update, context: ContextTypes\.DEFAULT_TYPE\):)'
ENTRY_HANDLERS = ['entry_from_menu', 'cmd_quiz', 'cmd_start', 'start_task']
MODE_HANDLERS = ['select_mode', 'practice_mode', 'theory_mode', 'progress_mode', 'settings_mode']
ANSWER_HANDLERS = ['check_answer', 'handle_answer', 'handle_mistake_answer']
NAV_HANDLERS = ['back_to_menu', 'back_to_mode', 'show_main_menu']

# Маппинг обработчиков на требуемые состояния
HANDLER_STATE_MAP = {
    # Entry points
    'entry_from_menu': '{ConversationHandler.END, None}',
    'cmd_quiz': '{ConversationHandler.END, None}',
    'cmd_start': '{ConversationHandler.END, None}',
    
    # Mode selection handlers
    'select_exam_num_mode': '{states.CHOOSING_MODE}',
    'select_block_mode': '{states.CHOOSING_MODE}',
    'select_random_all': '{states.CHOOSING_MODE}',
    'select_mistakes_mode': '{states.CHOOSING_MODE}',
    'practice_mode': '{states.CHOOSING_MODE}',
    'theory_mode': '{states.CHOOSING_MODE}',
    'progress_mode': '{states.CHOOSING_MODE}',
    'settings_mode': '{states.CHOOSING_MODE}',
    'show_blocks': '{states.CHOOSING_MODE}',
    'train_mode': '{states.CHOOSING_MODE}',
    'exam_mode': '{states.CHOOSING_MODE}',
    
    # Block/Topic selection
    'select_block': '{states.CHOOSING_BLOCK}',
    'select_topic': '{states.CHOOSING_TOPIC}',
    'choose_topic_list': '{states.CHOOSING_MODE}',
    'select_topic_from_block': '{states.CHOOSING_BLOCK}',
    
    # Answer handlers
    'check_answer': '{states.ANSWERING}',
    'handle_answer': '{states.ANSWERING}',
    'handle_mistake_answer': '{states.REVIEWING_MISTAKES}',
    'handle_full_answer': '{states.ANSWERING}',
    'handle_part_answer': '{states.ANSWERING_PARTS}',
    
    # Navigation handlers (multiple states)
    'back_to_menu': '{states.CHOOSING_MODE, states.CHOOSING_BLOCK, states.CHOOSING_TOPIC, states.ANSWERING}',
    'back_to_mode': '{states.CHOOSING_MODE, states.CHOOSING_BLOCK, states.CHOOSING_TOPIC, states.CHOOSING_EXAM_NUMBER}',
    'back_to_main_menu': '{states.CHOOSING_MODE, states.CHOOSING_BLOCK, states.CHOOSING_TOPIC, states.ANSWERING, states.ANSWERING_PARTS}',
    
    # Next action handlers
    'handle_next_action': '{states.CHOOSING_NEXT_ACTION}',
    'mistake_nav': '{states.REVIEWING_MISTAKES, states.CHOOSING_MODE}',
    
    # Specific task handlers
    'start_task': '{states.CHOOSING_MODE, states.CHOOSING_TOPIC}',
    'apply_strictness': '{states.CHOOSING_MODE}',
    'show_criteria': '{states.CHOOSING_MODE}',
    'show_settings': '{states.CHOOSING_MODE}',
}


class HandlersUpdater:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.content = ""
        self.updated_content = ""
        self.handlers_found = []
        self.handlers_updated = []
        
    def read_file(self):
        """Читает содержимое файла."""
        with open(self.file_path, 'r', encoding='utf-8') as f:
            self.content = f.read()
        
    def create_backup(self):
        """Создает резервную копию файла."""
        backup_dir = os.path.join(os.path.dirname(self.file_path), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(
            backup_dir, 
            f"{os.path.basename(self.file_path)}.{timestamp}.bak"
        )
        
        shutil.copy2(self.file_path, backup_path)
        print(f"✅ Создана резервная копия: {backup_path}")
        
    def add_imports(self):
        """Добавляет необходимые импорты если их нет."""
        imports_to_add = [
            "from core.state_validator import validate_state_transition, state_validator",
            "from telegram.ext import ConversationHandler"
        ]
        
        # Проверяем наличие импортов
        for import_line in imports_to_add:
            if import_line not in self.content:
                # Ищем место для вставки после других импортов из core
                import_pattern = r'(from core\.[^\n]+\n)'
                matches = list(re.finditer(import_pattern, self.content))
                
                if matches:
                    # Вставляем после последнего импорта из core
                    last_match = matches[-1]
                    insert_pos = last_match.end()
                    self.content = (
                        self.content[:insert_pos] + 
                        import_line + "\n" + 
                        self.content[insert_pos:]
                    )
                    print(f"✅ Добавлен импорт: {import_line}")
                else:
                    # Вставляем в начало файла после первых импортов
                    first_import = re.search(r'(import [^\n]+\n|from [^\n]+\n)', self.content)
                    if first_import:
                        insert_pos = first_import.end()
                        self.content = (
                            self.content[:insert_pos] + 
                            "\n" + import_line + "\n" + 
                            self.content[insert_pos:]
                        )
    
    def find_handlers(self):
        """Находит все обработчики в файле."""
        # Паттерн для поиска async функций с @safe_handler
        pattern = r'@safe_handler\(\)[^\n]*\nasync def (\w+)\([^)]+\):'
        
        matches = re.finditer(pattern, self.content)
        for match in matches:
            handler_name = match.group(1)
            self.handlers_found.append((handler_name, match.start()))
            
        print(f"🔍 Найдено обработчиков: {len(self.handlers_found)}")
        
    def update_handler(self, handler_name: str, start_pos: int) -> str:
        """Обновляет конкретный обработчик."""
        # Проверяем, есть ли уже декоратор validate_state_transition
        check_pattern = (
            r'@safe_handler\(\)[^\n]*\n'
            r'(@validate_state_transition[^\n]*\n)?'
            r'async def ' + handler_name
        )
        
        match = re.search(check_pattern, self.content[start_pos:start_pos+500])
        if match and match.group(1):  # Уже есть декоратор
            print(f"⏭️ {handler_name} - уже имеет валидацию")
            return self.content
        
        # Получаем требуемые состояния для обработчика
        required_states = HANDLER_STATE_MAP.get(handler_name)
        
        if not required_states:
            # Пытаемся определить по шаблону имени
            if handler_name.startswith('entry_') or handler_name.startswith('cmd_'):
                required_states = '{ConversationHandler.END, None}'
            elif 'mode' in handler_name or 'select_' in handler_name:
                required_states = '{states.CHOOSING_MODE}'
            elif 'answer' in handler_name:
                required_states = '{states.ANSWERING}'
            elif 'back_' in handler_name or 'nav' in handler_name:
                required_states = '{states.CHOOSING_MODE}'
            else:
                print(f"⚠️ {handler_name} - не удалось определить состояния")
                return self.content
        
        # Добавляем декоратор
        pattern = r'(@safe_handler\(\))\n(async def ' + handler_name + r'\([^)]+\):)'
        replacement = (
            r'\1\n'
            r'@validate_state_transition(' + required_states + r')\n'
            r'\2'
        )
        
        new_content = re.sub(pattern, replacement, self.content)
        
        if new_content != self.content:
            self.handlers_updated.append(handler_name)
            print(f"✅ {handler_name} - добавлена валидация {required_states}")
            return new_content
        
        return self.content
    
    def update_all_handlers(self):
        """Обновляет все найденные обработчики."""
        self.updated_content = self.content
        
        # Сортируем по позиции в обратном порядке чтобы не сбить индексы
        sorted_handlers = sorted(self.handlers_found, key=lambda x: x[1], reverse=True)
        
        for handler_name, start_pos in sorted_handlers:
            self.updated_content = self.update_handler(handler_name, 0)
            self.content = self.updated_content
    
    def save_file(self):
        """Сохраняет обновленный файл."""
        with open(self.file_path, 'w', encoding='utf-8') as f:
            f.write(self.updated_content)
        
        print(f"\n✅ Файл обновлен: {self.file_path}")
        print(f"   Обработчиков обновлено: {len(self.handlers_updated)}")
    
    def process(self):
        """Основной процесс обновления."""
        print(f"\n📁 Обработка файла: {self.file_path}")
        
        if not os.path.exists(self.file_path):
            print(f"❌ Файл не найден: {self.file_path}")
            return
        
        self.read_file()
        self.create_backup()
        self.add_imports()
        self.find_handlers()
        self.update_all_handlers()
        
        if self.handlers_updated:
            self.save_file()
        else:
            print("ℹ️ Нет обработчиков для обновления")


def main():
    """Главная функция."""
    print("🚀 Скрипт миграции обработчиков для валидации состояний\n")
    
    # Список файлов для обработки
    handler_files = [
        'test_part/handlers.py',
        'task19/handlers.py',
        'task20/handlers.py',
        'task24/handlers.py',
        'task25/handlers.py',
    ]
    
    # Добавляем missing_handlers если есть
    if os.path.exists('test_part/missing_handlers.py'):
        handler_files.append('test_part/missing_handlers.py')
    
    total_updated = 0
    
    for file_path in handler_files:
        updater = HandlersUpdater(file_path)
        updater.process()
        total_updated += len(updater.handlers_updated)
    
    print(f"\n✨ Миграция завершена!")
    print(f"   Всего обновлено обработчиков: {total_updated}")
    print(f"\n⚠️ Рекомендации:")
    print("1. Проверьте обновленные файлы")
    print("2. Запустите тесты")
    print("3. При необходимости откорректируйте состояния вручную")
    print("4. Резервные копии сохранены в папках backups/")


if __name__ == "__main__":
    main()