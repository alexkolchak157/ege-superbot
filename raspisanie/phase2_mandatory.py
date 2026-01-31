"""
Фаза 2: Размещение обязательных предметов
TODO: Реализовать алгоритм
"""

from typing import List, Optional
from schedule_base import *
from data_loader import DataLoader


class Phase2MandatoryPlacer:
    """Класс для размещения обязательных предметов"""
    
    def __init__(self, schedule: Schedule, loader: DataLoader, ege_slots: List[TimeSlot]):
        self.schedule = schedule
        self.loader = loader
        self.ege_slots = ege_slots  # Слоты, занятые практикумами ЕГЭ
        
        # Все возможные слоты кроме зарезервированных для ЕГЭ
        self.available_slots = [
            TimeSlot(day, lesson)
            for day in DayOfWeek
            for lesson in range(1, 8)
            if TimeSlot(day, lesson) not in ege_slots
        ]
    
    def place_all_mandatory_subjects(self):
        """
        Разместить все обязательные предметы
        
        Алгоритм:
        1. Получить список всех обязательных предметов
        2. Отсортировать по приоритету
        3. Для каждого предмета найти лучшие слоты и разместить
        """
        print("\n🔧 Размещение обязательных предметов...")
        
        # TODO: Получить обязательные предметы
        mandatory_subjects = [
            s for s in self.loader.subjects
            if s.subject_type == SubjectType.MANDATORY
        ]
        
        print(f"Найдено {len(mandatory_subjects)} обязательных предметов")
        
        # TODO: Отсортировать по приоритету
        # 1. Предметы с большим количеством часов
        # 2. Сложные предметы (математика, русский, физика)
        mandatory_subjects.sort(
            key=lambda s: (s.hours_per_week, self._is_hard_subject(s)),
            reverse=True
        )
        
        # TODO: Разместить каждый предмет
        placed_total = 0
        for subject in mandatory_subjects:
            placed = self._place_subject(subject)
            placed_total += placed
            
            if placed < subject.hours_per_week:
                print(f"⚠️  {subject.name}: размещено {placed}/{subject.hours_per_week} уроков")
        
        print(f"\n✅ Размещено {placed_total} обязательных уроков")
    
    def _place_subject(self, subject: Subject) -> int:
        """
        Разместить один предмет
        
        Returns:
            Количество размещенных уроков
        """
        placed = 0
        is_hard = self._is_hard_subject(subject)
        
        # TODO: Найти лучшие слоты для этого предмета
        scored_slots = []
        for slot in self.available_slots:
            score = self._evaluate_slot(slot, subject, is_hard)
            if score > 0:  # Слот доступен
                scored_slots.append((score, slot))
        
        # Сортируем по убыванию качества
        scored_slots.sort(reverse=True)
        
        # TODO: Размещаем уроки в лучшие слоты
        for score, slot in scored_slots:
            if placed >= subject.hours_per_week:
                break
            
            # Проверяем, можно ли разместить урок
            if not self._can_place_lesson(subject, slot):
                continue
            
            # Находим кабинет
            classroom = self._find_classroom(subject, slot)
            if not classroom:
                continue
            
            # Создаем урок
            lesson = Lesson(
                subject=subject.name,
                teacher=subject.teacher,
                class_or_group=subject.classes[0] if subject.classes else "???",
                classroom=classroom,
                time_slot=slot,
                is_ege_practice=False
            )
            
            self.schedule.add_lesson(lesson)
            placed += 1
        
        return placed
    
    def _evaluate_slot(self, slot: TimeSlot, subject: Subject, is_hard: bool) -> float:
        """
        Оценить качество слота для предмета
        
        Returns:
            Оценка (больше = лучше, 0 = недоступен)
        """
        score = 100.0
        
        # TODO: Проверить доступность учителя
        if not subject.teacher.is_available(slot.day):
            return 0.0
        
        if self.schedule.is_teacher_busy(subject.teacher, slot):
            return 0.0
        
        # TODO: Проверить доступность класса
        for class_name in subject.classes:
            if self.schedule.is_class_busy(class_name, slot):
                return 0.0
        
        # TODO: Бонус за оптимальное время для сложных предметов
        if is_hard and 2 <= slot.lesson_number <= 4:
            score += 30
        elif not is_hard and slot.lesson_number >= 5:
            score += 10  # Легкие предметы лучше после обеда
        
        # TODO: Штраф за первый и последний урок
        if slot.lesson_number == 1:
            score -= 10
        if slot.lesson_number == 7:
            score -= 20
        
        # TODO: Учесть текущую загруженность дня
        day_lessons = [l for l in self.schedule.lessons if l.time_slot.day == slot.day]
        score -= len(day_lessons) * 2  # Штраф за перегруженные дни
        
        return score
    
    def _can_place_lesson(self, subject: Subject, slot: TimeSlot) -> bool:
        """Проверить, можно ли разместить урок"""
        # TODO: Проверить учителя, классы, кабинеты
        
        if not subject.teacher.is_available(slot.day):
            return False
        
        if self.schedule.is_teacher_busy(subject.teacher, slot):
            return False
        
        for class_name in subject.classes:
            if self.schedule.is_class_busy(class_name, slot):
                return False
        
        return True
    
    def _find_classroom(self, subject: Subject, slot: TimeSlot) -> Optional[Classroom]:
        """Найти подходящий свободный кабинет"""
        # TODO: Реализовать поиск кабинета
        
        # Предпочитаем домашний кабинет учителя
        if subject.teacher.home_classroom:
            home_room = self.loader.classrooms.get(subject.teacher.home_classroom)
            if home_room and not self.schedule.is_classroom_busy(home_room, slot):
                return home_room
        
        # Ищем любой свободный кабинет
        for classroom in self.loader.classrooms.values():
            if not self.schedule.is_classroom_busy(classroom, slot):
                return classroom
        
        return None
    
    def _is_hard_subject(self, subject: Subject) -> bool:
        """Проверить, является ли предмет сложным"""
        hard_subjects = [
            'математика', 'русский', 'физика', 'химия',
            'английский', 'алгебра', 'геометрия'
        ]
        
        return any(hard in subject.name.lower() for hard in hard_subjects)


# Пример использования
if __name__ == '__main__':
    from data_loader import DataLoader
    from schedule_generator import ScheduleGenerator
    
    # Загрузка данных
    loader = DataLoader()
    loader.load_classrooms('data/Здания__кабинеты__места__школьные_здания_.xlsx')
    loader.load_teachers_and_subjects('data/Расстановка_кадров_ФЕВРАЛЬ_2025-2026_учебный_год__2_.xlsx')
    loader.load_students_and_ege_choices('data/Список_участников_ГИА-11_ГБОУ_Школа__Покровский_квартал___41_.xlsx')
    loader.create_ege_practice_groups()
    
    # Фаза 1
    generator = ScheduleGenerator(loader)
    generator.place_ege_practices()
    
    # Фаза 2
    phase2 = Phase2MandatoryPlacer(
        schedule=generator.schedule,
        loader=loader,
        ege_slots=generator.ege_slots
    )
    phase2.place_all_mandatory_subjects()
    
    print(f"\n✅ Всего уроков: {len(generator.schedule.lessons)}")
