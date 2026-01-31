"""
Фаза 3: Оптимизация расписания
TODO: Реализовать алгоритм
"""

from typing import List, Tuple
from schedule_base import *
from data_loader import DataLoader
import random
import copy


class Phase3Optimizer:
    """Класс для оптимизации расписания"""
    
    def __init__(self, schedule: Schedule, loader: DataLoader):
        self.schedule = schedule
        self.loader = loader
    
    def optimize(self, max_iterations: int = 1000):
        """
        Оптимизировать расписание
        
        Использует алгоритм simulated annealing:
        1. Подсчитать текущую метрику качества
        2. Случайно выбрать два урока для обмена
        3. Если обмен улучшает метрику - применить
        4. Если ухудшает - применить с некоторой вероятностью (для выхода из локальных минимумов)
        5. Повторить N раз
        """
        print("\n🔧 Оптимизация расписания...")
        
        current_metric = self._calculate_quality_metric()
        best_metric = current_metric
        best_schedule = copy.deepcopy(self.schedule)
        
        print(f"Начальная метрика: {current_metric:.2f}")
        
        temperature = 100.0  # Начальная "температура" для simulated annealing
        cooling_rate = 0.995  # Скорость охлаждения
        
        improvements = 0
        
        for iteration in range(max_iterations):
            # TODO: Найти пару уроков для обмена
            lesson1, lesson2 = self._find_swap_candidates()
            
            if not lesson1 or not lesson2:
                continue
            
            # TODO: Обменять уроки
            old_slot1 = lesson1.time_slot
            old_slot2 = lesson2.time_slot
            
            lesson1.time_slot = old_slot2
            lesson2.time_slot = old_slot1
            
            # TODO: Проверить метрику
            new_metric = self._calculate_quality_metric()
            delta = new_metric - current_metric
            
            # Решение: принять или откатить обмен
            if delta < 0:  # Улучшение (меньше метрика = лучше)
                current_metric = new_metric
                improvements += 1
                
                if new_metric < best_metric:
                    best_metric = new_metric
                    best_schedule = copy.deepcopy(self.schedule)
                    print(f"  Итерация {iteration}: новый лучший результат = {best_metric:.2f}")
            
            elif random.random() < self._acceptance_probability(delta, temperature):
                # Принимаем ухудшающий обмен с некоторой вероятностью
                current_metric = new_metric
            
            else:
                # Откатываем обмен
                lesson1.time_slot = old_slot1
                lesson2.time_slot = old_slot2
            
            # Охлаждение
            temperature *= cooling_rate
        
        # Восстанавливаем лучший найденный вариант
        self.schedule = best_schedule
        
        print(f"\n✅ Оптимизация завершена")
        print(f"   Итераций: {max_iterations}")
        print(f"   Улучшений: {improvements}")
        print(f"   Финальная метрика: {best_metric:.2f}")
    
    def _calculate_quality_metric(self) -> float:
        """
        Подсчитать метрику качества расписания
        
        Меньше = лучше
        
        Учитывает:
        - Количество окон у учителей (вес: 4)
        - Количество окон у классов (вес: 4)
        - Отклонение от равномерной нагрузки (вес: 3)
        - Количество уроков вне оптимального времени (вес: 4)
        """
        metric = 0.0
        
        # TODO: 1. Окна у учителей (очень важно)
        teacher_gaps = sum(
            self.schedule.get_teacher_gaps(teacher)
            for teacher in self.loader.teachers.values()
        )
        metric += teacher_gaps * 4  # Вес = 4
        
        # TODO: 2. Окна у классов (очень важно)
        class_gaps = sum(
            self.schedule.get_class_gaps(class_name)
            for class_name in self.loader.classes.keys()
        )
        metric += class_gaps * 4  # Вес = 4
        
        # TODO: 3. Неравномерная нагрузка по дням (средняя важность)
        load_variance = self._calculate_daily_load_variance()
        metric += load_variance * 3  # Вес = 3
        
        # TODO: 4. Уроки вне оптимального времени (очень важно)
        suboptimal_timing = self._count_suboptimal_timing()
        metric += suboptimal_timing * 4  # Вес = 4
        
        return metric
    
    def _calculate_daily_load_variance(self) -> float:
        """
        Подсчитать дисперсию нагрузки по дням недели
        
        Чем равномернее распределены уроки по дням, тем меньше метрика
        """
        # TODO: Подсчитать количество уроков в каждый день
        daily_loads = []
        
        for day in DayOfWeek:
            day_lessons = [l for l in self.schedule.lessons if l.time_slot.day == day]
            daily_loads.append(len(day_lessons))
        
        # Вычисляем стандартное отклонение
        if not daily_loads:
            return 0.0
        
        mean = sum(daily_loads) / len(daily_loads)
        variance = sum((x - mean) ** 2 for x in daily_loads) / len(daily_loads)
        
        return variance ** 0.5  # Стандартное отклонение
    
    def _count_suboptimal_timing(self) -> int:
        """
        Подсчитать количество уроков в неоптимальное время
        
        Оптимальное время для сложных предметов: 2-4 урок
        """
        count = 0
        
        hard_subjects = ['математика', 'русский', 'физика', 'химия', 'английский']
        
        for lesson in self.schedule.lessons:
            is_hard = any(subj in lesson.subject.lower() for subj in hard_subjects)
            
            if is_hard and lesson.time_slot.lesson_number not in [2, 3, 4]:
                count += 1
        
        return count
    
    def _find_swap_candidates(self) -> Tuple[Optional[Lesson], Optional[Lesson]]:
        """
        Найти два урока, которые можно обменять местами
        
        Returns:
            (lesson1, lesson2) или (None, None)
        """
        # TODO: Случайно выбираем два урока
        if len(self.schedule.lessons) < 2:
            return None, None
        
        lessons = list(self.schedule.lessons)
        random.shuffle(lessons)
        
        for i, lesson1 in enumerate(lessons):
            for lesson2 in lessons[i+1:]:
                if self._can_swap(lesson1, lesson2):
                    return lesson1, lesson2
        
        return None, None
    
    def _can_swap(self, lesson1: Lesson, lesson2: Lesson) -> bool:
        """
        Проверить, можно ли обменять два урока местами
        
        Проверяет, что после обмена не будет конфликтов
        """
        # TODO: Проверить, что учителя не заняты
        
        # Проверяем учителя lesson1 в слоте lesson2
        for other_lesson in self.schedule.lessons:
            if other_lesson == lesson1 or other_lesson == lesson2:
                continue
            
            if (other_lesson.teacher == lesson1.teacher and 
                other_lesson.time_slot == lesson2.time_slot):
                return False
        
        # Проверяем учителя lesson2 в слоте lesson1
        for other_lesson in self.schedule.lessons:
            if other_lesson == lesson1 or other_lesson == lesson2:
                continue
            
            if (other_lesson.teacher == lesson2.teacher and 
                other_lesson.time_slot == lesson1.time_slot):
                return False
        
        # TODO: Аналогично проверить классы
        
        return True
    
    def _acceptance_probability(self, delta: float, temperature: float) -> float:
        """
        Вероятность принятия ухудшающего обмена (simulated annealing)
        
        Формула: e^(-delta / temperature)
        """
        if temperature == 0:
            return 0.0
        
        import math
        return math.exp(-delta / temperature)
    
    def print_statistics(self):
        """Вывести статистику после оптимизации"""
        print("\n" + "="*100)
        print("СТАТИСТИКА ПОСЛЕ ОПТИМИЗАЦИИ")
        print("="*100)
        
        # Окна
        teacher_gaps = sum(
            self.schedule.get_teacher_gaps(teacher)
            for teacher in self.loader.teachers.values()
        )
        print(f"\n🕳️  Окон у учителей: {teacher_gaps}")
        
        class_gaps = sum(
            self.schedule.get_class_gaps(class_name)
            for class_name in self.loader.classes.keys()
        )
        print(f"🕳️  Окон у классов: {class_gaps}")
        
        # Нагрузка по дням
        print(f"\n📊 Нагрузка по дням:")
        for day in DayOfWeek:
            day_lessons = [l for l in self.schedule.lessons if l.time_slot.day == day]
            print(f"   {day.name:10s}: {len(day_lessons):3d} уроков")
        
        # Топ-3 учителей с окнами
        print(f"\n👨‍🏫 Топ-3 учителей с наибольшим количеством окон:")
        teacher_gap_list = [
            (teacher.name, self.schedule.get_teacher_gaps(teacher))
            for teacher in self.loader.teachers.values()
        ]
        teacher_gap_list.sort(key=lambda x: x[1], reverse=True)
        
        for i, (teacher_name, gaps) in enumerate(teacher_gap_list[:3], 1):
            print(f"   {i}. {teacher_name:30s}: {gaps} окон")
        
        print("="*100)


# Пример использования
if __name__ == '__main__':
    from data_loader import DataLoader
    from schedule_generator import ScheduleGenerator
    from phase2_mandatory import Phase2MandatoryPlacer
    
    # Загрузка данных
    loader = DataLoader()
    loader.load_classrooms('data/Здания__кабинеты__места__школьные_здания_.xlsx')
    loader.load_teachers_and_subjects('data/Расстановка_кадров_ФЕВРАЛЬ_2025-2026_учебный_год__2_.xlsx')
    loader.load_students_and_ege_choices('data/Список_участников_ГИА-11_ГБОУ_Школа__Покровский_квартал___41_.xlsx')
    loader.create_ege_practice_groups()
    
    # Фаза 1
    generator = ScheduleGenerator(loader)
    generator.place_ege_practices()
    
    # Фаза 2 (если реализована)
    # phase2 = Phase2MandatoryPlacer(...)
    # phase2.place_all_mandatory_subjects()
    
    # Фаза 3
    optimizer = Phase3Optimizer(
        schedule=generator.schedule,
        loader=loader
    )
    optimizer.optimize(max_iterations=1000)
    optimizer.print_statistics()
