"""
Главный файл для запуска генератора расписания
"""

import sys
import argparse
from pathlib import Path
from data_loader import DataLoader
from schedule_generator import ScheduleGenerator


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(description='Генератор расписания для школы')
    
    parser.add_argument('--data-dir', type=str, default='data',
                       help='Папка с исходными данными')
    parser.add_argument('--output-dir', type=str, default='output',
                       help='Папка для результатов')
    parser.add_argument('--phase', type=str, default='all',
                       choices=['all', '1', '2', '3'],
                       help='Какую фазу запустить (all/1/2/3)')
    
    args = parser.parse_args()
    
    print("="*100)
    print(" " * 25 + "ГЕНЕРАТОР РАСПИСАНИЯ v0.1")
    print("="*100)
    
    # Проверка наличия папки с данными
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"❌ Папка с данными не найдена: {data_dir}")
        print(f"   Создайте папку '{args.data_dir}' и поместите туда Excel файлы")
        return 1
    
    # Проверка наличия файлов
    required_files = [
        'Здания__кабинеты__места__школьные_здания_.xlsx',
        'Расстановка_кадров_ФЕВРАЛЬ_2025-2026_учебный_год__2_.xlsx',
        'Список_участников_ГИА-11_ГБОУ_Школа__Покровский_квартал___41_.xlsx'
    ]
    
    missing_files = []
    for filename in required_files:
        if not (data_dir / filename).exists():
            missing_files.append(filename)
    
    if missing_files:
        print("❌ Отсутствуют необходимые файлы:")
        for f in missing_files:
            print(f"   - {f}")
        return 1
    
    # Создание папки для результатов
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    
    print("\n📂 Загрузка данных...")
    
    # Загрузка данных
    loader = DataLoader()
    
    try:
        loader.load_classrooms(str(data_dir / 'Здания__кабинеты__места__школьные_здания_.xlsx'))
        loader.load_teachers_and_subjects(str(data_dir / 'Расстановка_кадров_ФЕВРАЛЬ_2025-2026_учебный_год__2_.xlsx'))
        loader.load_students_and_ege_choices(str(data_dir / 'Список_участников_ГИА-11_ГБОУ_Школа__Покровский_квартал___41_.xlsx'))
        loader.create_ege_practice_groups()
        
        loader.print_summary()
        
    except Exception as e:
        print(f"❌ Ошибка при загрузке данных: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Генерация расписания
    print("\n🔧 Генерация расписания...")
    generator = ScheduleGenerator(loader)
    
    try:
        # Фаза 1: Практикумы ЕГЭ
        if args.phase in ['all', '1']:
            print("\n" + "="*100)
            print("ФАЗА 1: РАЗМЕЩЕНИЕ ПРАКТИКУМОВ ЕГЭ")
            print("="*100)
            generator.place_ege_practices()
            
            # Сохранение промежуточного результата
            generator.schedule.save_to_json(str(output_dir / 'schedule_phase1.json'))
            print(f"\n💾 Фаза 1 сохранена: {output_dir / 'schedule_phase1.json'}")
        
        # Фаза 2: Обязательные предметы (TODO)
        if args.phase in ['all', '2']:
            print("\n" + "="*100)
            print("ФАЗА 2: РАЗМЕЩЕНИЕ ОБЯЗАТЕЛЬНЫХ ПРЕДМЕТОВ")
            print("="*100)
            print("⚠️  Фаза 2 пока не реализована")
            print("   Нужно создать файл phase2_mandatory.py")
            # generator.place_mandatory_subjects()
        
        # Фаза 3: Оптимизация (TODO)
        if args.phase in ['all', '3']:
            print("\n" + "="*100)
            print("ФАЗА 3: ОПТИМИЗАЦИЯ РАСПИСАНИЯ")
            print("="*100)
            print("⚠️  Фаза 3 пока не реализована")
            print("   Нужно создать файл phase3_optimization.py")
            # generator.optimize_schedule()
        
        # Финальное сохранение
        generator.schedule.save_to_json(str(output_dir / 'schedule_final.json'))
        print(f"\n✅ Расписание сохранено: {output_dir / 'schedule_final.json'}")
        
        # Статистика
        print("\n" + "="*100)
        print("СТАТИСТИКА")
        print("="*100)
        print(f"Всего уроков: {len(generator.schedule.lessons)}")
        print(f"Практикумов ЕГЭ: {sum(1 for l in generator.schedule.lessons if l.is_ege_practice)}")
        
        # Подсчет окон
        total_gaps = sum(generator.schedule.get_teacher_gaps(t) 
                        for t in loader.teachers.values())
        print(f"Окон у учителей: {total_gaps}")
        
        print("\n✅ Генерация завершена успешно!")
        print("="*100)
        
        return 0
        
    except Exception as e:
        print(f"❌ Ошибка при генерации расписания: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
