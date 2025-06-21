#!/usr/bin/env python3
"""
Автоматический тестер унификации UI/UX
Проверяет все модули на соответствие стандартам
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

class UnificationTester:
    def __init__(self):
        self.modules = ['task19', 'task20', 'task24', 'task25', 'test_part']
        self.results = {}
        
    def check_imports(self, filepath: str) -> Tuple[bool, List[str]]:
        """Проверяет наличие импортов универсальных компонентов"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        required_imports = [
            'UniversalUIComponents',
            'AdaptiveKeyboards', 
            'MessageFormatter'
        ]
        
        missing = []
        for imp in required_imports:
            if imp not in content:
                missing.append(imp)
        
        return len(missing) == 0, missing
    
    def check_universal_usage(self, filepath: str) -> Dict[str, int]:
        """Подсчитывает использование универсальных компонентов"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        usage = {
            'UniversalUIComponents': len(re.findall(r'UniversalUIComponents\.', content)),
            'AdaptiveKeyboards': len(re.findall(r'AdaptiveKeyboards\.', content)),
            'MessageFormatter': len(re.findall(r'MessageFormatter\.', content)),
            'create_progress_bar': len(re.findall(r'create_progress_bar\(', content)),
            'create_score_visual': len(re.findall(r'create_score_visual\(', content)),
            'format_result_message': len(re.findall(r'format_result_message\(', content)),
            'format_progress_message': len(re.findall(r'format_progress_message\(', content)),
            'create_result_keyboard': len(re.findall(r'create_result_keyboard\(', content)),
            'create_menu_keyboard': len(re.findall(r'create_menu_keyboard\(', content)),
        }
        
        return usage
    
    def check_old_components(self, filepath: str) -> List[str]:
        """Проверяет наличие старых компонентов"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Используем регулярные выражения для точного совпадения названий
        regex_patterns = [
            ('UIComponents', re.compile(r'\bUIComponents\b')),
            ('EnhancedKeyboards', re.compile(r'\bEnhancedKeyboards\b')),
        ]

        string_patterns = [
            'from .ui_components',
            'from .user_interface',
            '█' * 10,  # Старые прогресс-бары
            '▓' * 10,
        ]

        found = []
        for label, regex in regex_patterns:
            if regex.search(content):
                found.append(label)

        for pattern in string_patterns:
            if pattern in content:
                found.append(pattern)
        
        return found
    
    def check_callbacks(self, filepath: str) -> Dict[str, List[str]]:
        """Проверяет стандартизацию callback_data"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Извлекаем все callback_data
        callbacks = re.findall(r'callback_data="([^"]+)"', content)
        
        module_code = filepath.split('/')[0].replace('task', 't')
        if module_code == 'test_part':
            module_code = 'test'
        
        non_standard = []
        standard = []
        
        for cb in callbacks:
            if cb == 'to_main_menu' or cb == 'noop':
                standard.append(cb)
            elif cb.startswith(f"{module_code}_"):
                standard.append(cb)
            else:
                non_standard.append(cb)
        
        return {'standard': standard, 'non_standard': non_standard}
    
    def test_module(self, module: str):
        """Тестирует один модуль"""
        print(f"\n🔍 Тестирование {module}...")
        
        handlers_path = f"{module}/handlers.py"
        plugin_path = f"{module}/plugin.py"
        
        results = {
            'imports': False,
            'usage': {},
            'old_components': [],
            'callbacks': {},
            'score': 0
        }
        
        if os.path.exists(handlers_path):
            # Проверяем импорты
            imports_ok, missing = self.check_imports(handlers_path)
            results['imports'] = imports_ok
            results['missing_imports'] = missing
            
            # Проверяем использование
            results['usage'] = self.check_universal_usage(handlers_path)
            
            # Проверяем старые компоненты
            results['old_components'] = self.check_old_components(handlers_path)
            
            # Проверяем callbacks
            results['callbacks'] = self.check_callbacks(handlers_path)
            
            # Подсчитываем score
            score = 0
            if imports_ok:
                score += 20
            
            # За использование компонентов
            total_usage = sum(results['usage'].values())
            if total_usage > 0:
                score += min(40, total_usage * 5)
            
            # За отсутствие старых компонентов
            if not results['old_components']:
                score += 20
            
            # За стандартные callbacks
            if results['callbacks']:
                total_callbacks = len(results['callbacks']['standard']) + len(results['callbacks']['non_standard'])
                if total_callbacks:
                    std_ratio = len(results['callbacks']['standard']) / total_callbacks
                else:
                    std_ratio = 1.0
                score += round(std_ratio * 20)
            
            results['score'] = min(100, score)
        
        self.results[module] = results
        return results
    
    def print_report(self):
        """Выводит отчет"""
        print("\n" + "=" * 60)
        print("📊 ОТЧЕТ ПО УНИФИКАЦИИ UI/UX")
        print("=" * 60)
        
        total_score = 0
        
        for module, results in self.results.items():
            score = results['score']
            total_score += score
            
            # Выбираем эмодзи по score
            if score >= 90:
                status = "✅"
            elif score >= 70:
                status = "⚠️"
            else:
                status = "❌"
            
            print(f"\n{status} {module}: {score}%")
            
            # Детали
            if not results['imports']:
                print(f"   ❌ Отсутствуют импорты: {', '.join(results['missing_imports'])}")
            
            usage = results['usage']
            if sum(usage.values()) == 0:
                print("   ❌ Универсальные компоненты не используются")
            else:
                print(f"   ✅ Использований компонентов: {sum(usage.values())}")
            
            if results['old_components']:
                print(f"   ❌ Найдены старые компоненты: {', '.join(results['old_components'][:3])}")
            
            if results['callbacks'].get('non_standard'):
                print(f"   ⚠️ Нестандартные callback: {', '.join(results['callbacks']['non_standard'][:3])}")
        
        avg_score = total_score / len(self.results)
        
        print("\n" + "=" * 60)
        print(f"ОБЩИЙ ПРОГРЕСС УНИФИКАЦИИ: {avg_score:.1f}%")
        print("=" * 60)
        
        if avg_score >= 90:
            print("🎉 Отличная работа! Унификация почти завершена!")
        elif avg_score >= 70:
            print("👍 Хороший прогресс! Осталось немного доработать.")
        else:
            print("⚠️ Требуется значительная доработка для полной унификации.")
    
    def run(self):
        """Запускает тестирование"""
        print("🧪 Запуск автоматического тестера унификации...\n")
        
        for module in self.modules:
            if os.path.exists(module):
                self.test_module(module)
            else:
                print(f"⚠️ Модуль {module} не найден")
        
        self.print_report()

if __name__ == "__main__":
    tester = UnificationTester()
    tester.run()