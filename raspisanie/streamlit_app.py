"""
Веб-интерфейс для генератора расписания
ГБОУ "Школа Покровский квартал"

Запуск: streamlit run streamlit_app.py
"""

import streamlit as st
import pandas as pd
import json
from pathlib import Path
from io import BytesIO

# Импорты модулей расписания
from schedule_base import Schedule, DayOfWeek, TimeSlot
from demo_data import DemoDataLoader
from schedule_generator import ScheduleGenerator
from phase2_mandatory import Phase2MandatoryPlacer
from phase3_optimization import Phase3Optimizer

# Настройка страницы
st.set_page_config(
    page_title="Генератор расписания",
    page_icon="📅",
    layout="wide"
)


def main():
    st.title("📅 Генератор расписания")
    st.markdown("**ГБОУ \"Школа Покровский квартал\"** (корпус БК)")
    st.markdown("---")

    # Боковая панель
    with st.sidebar:
        st.header("⚙️ Настройки")

        # Источник данных
        data_source = st.radio(
            "Источник данных:",
            ["Демо-данные", "Загрузить Excel"]
        )

        st.markdown("---")

        # Параметры оптимизации
        st.subheader("Параметры оптимизации")
        iterations = st.slider(
            "Количество итераций",
            min_value=100,
            max_value=5000,
            value=1000,
            step=100
        )

        run_phase3 = st.checkbox("Запустить оптимизацию (Фаза 3)", value=True)

        st.markdown("---")

        # Кнопка генерации
        generate_button = st.button("🚀 Сгенерировать расписание", type="primary")

    # Основная область
    if generate_button:
        with st.spinner("Генерация расписания..."):
            schedule, loader, stats = generate_schedule(iterations, run_phase3)

            if schedule:
                st.session_state['schedule'] = schedule
                st.session_state['loader'] = loader
                st.session_state['stats'] = stats
                st.success("✅ Расписание сгенерировано!")

    # Отображение расписания
    if 'schedule' in st.session_state:
        schedule = st.session_state['schedule']
        loader = st.session_state['loader']
        stats = st.session_state['stats']

        # Вкладки
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 Статистика",
            "📚 По классам",
            "👨‍🏫 По учителям",
            "🏫 По кабинетам",
            "📥 Экспорт"
        ])

        with tab1:
            show_statistics(schedule, loader, stats)

        with tab2:
            show_by_class(schedule, loader)

        with tab3:
            show_by_teacher(schedule, loader)

        with tab4:
            show_by_classroom(schedule, loader)

        with tab5:
            show_export(schedule, loader)

    else:
        st.info("👆 Нажмите кнопку \"Сгенерировать расписание\" в боковой панели")

        # Показываем описание
        st.markdown("""
        ### О программе

        Эта программа автоматически составляет расписание для 11 классов с учетом:

        - **Практикумы ЕГЭ** — занятия по выбору учеников, проходящие одновременно для всех классов
        - **Обязательные предметы** — базовые уроки по учебному плану
        - **Оптимизация** — минимизация окон у учителей и классов

        #### Алгоритм работы

        1. **Фаза 1:** Размещение практикумов ЕГЭ в оптимальные слоты
        2. **Фаза 2:** Размещение обязательных предметов
        3. **Фаза 3:** Оптимизация методом Simulated Annealing
        """)


def generate_schedule(iterations: int, run_phase3: bool):
    """Генерация расписания"""

    # Прогресс-бар
    progress = st.progress(0)
    status = st.empty()

    # Загрузка данных
    status.text("📂 Загрузка данных...")
    loader = DemoDataLoader()
    loader.load_all()
    progress.progress(20)

    # Фаза 1
    status.text("🎯 Фаза 1: Размещение практикумов ЕГЭ...")
    generator = ScheduleGenerator(loader)
    generator.place_ege_practices()
    progress.progress(40)

    # Фаза 2
    status.text("📚 Фаза 2: Размещение обязательных предметов...")
    phase2 = Phase2MandatoryPlacer(
        schedule=generator.schedule,
        loader=loader,
        ege_slots=generator.ege_slots
    )
    phase2_stats = phase2.place_all_mandatory_subjects()
    progress.progress(60)

    # Фаза 3
    if run_phase3:
        status.text("🔧 Фаза 3: Оптимизация расписания...")
        optimizer = Phase3Optimizer(
            schedule=generator.schedule,
            loader=loader
        )
        schedule = optimizer.optimize(max_iterations=iterations, verbose=False)
        phase3_stats = optimizer.stats
    else:
        schedule = generator.schedule
        phase3_stats = None

    progress.progress(100)
    status.empty()

    stats = {
        'phase2': phase2_stats,
        'phase3': phase3_stats
    }

    return schedule, loader, stats


def show_statistics(schedule: Schedule, loader, stats: dict):
    """Показать статистику"""
    st.header("📊 Статистика расписания")

    # Метрики
    col1, col2, col3, col4 = st.columns(4)

    total_lessons = len(schedule.lessons)
    ege_lessons = sum(1 for l in schedule.lessons if l.is_ege_practice)
    mandatory_lessons = total_lessons - ege_lessons

    with col1:
        st.metric("Всего уроков", total_lessons)

    with col2:
        st.metric("Практикумы ЕГЭ", ege_lessons)

    with col3:
        st.metric("Обязательные", mandatory_lessons)

    with col4:
        success_rate = stats['phase2']['placed'] / stats['phase2']['total_required'] * 100
        st.metric("Успешность", f"{success_rate:.1f}%")

    st.markdown("---")

    # Окна
    col1, col2 = st.columns(2)

    with col1:
        teacher_gaps = sum(schedule.get_teacher_gaps(t) for t in loader.teachers.values())
        st.metric("🕳️ Окон у учителей", teacher_gaps)

    with col2:
        class_gaps = sum(schedule.get_class_gaps(c) for c in loader.classes.keys())
        st.metric("🕳️ Окон у классов", class_gaps)

    # Оптимизация
    if stats['phase3']:
        st.markdown("---")
        st.subheader("Результаты оптимизации")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Начальная метрика",
                f"{stats['phase3']['initial_metric']:.1f}"
            )

        with col2:
            st.metric(
                "Финальная метрика",
                f"{stats['phase3']['final_metric']:.1f}"
            )

        with col3:
            improvement = stats['phase3']['initial_metric'] - stats['phase3']['final_metric']
            pct = improvement / stats['phase3']['initial_metric'] * 100
            st.metric("Улучшение", f"{pct:.1f}%")

    # Нагрузка по дням
    st.markdown("---")
    st.subheader("📅 Нагрузка по дням недели")

    day_names = {
        DayOfWeek.MONDAY: "Понедельник",
        DayOfWeek.TUESDAY: "Вторник",
        DayOfWeek.WEDNESDAY: "Среда",
        DayOfWeek.THURSDAY: "Четверг",
        DayOfWeek.FRIDAY: "Пятница"
    }

    day_data = []
    for day in DayOfWeek:
        count = sum(1 for l in schedule.lessons if l.time_slot.day == day)
        day_data.append({"День": day_names[day], "Уроков": count})

    df = pd.DataFrame(day_data)
    st.bar_chart(df.set_index("День"))


def show_by_class(schedule: Schedule, loader):
    """Показать расписание по классам"""
    st.header("📚 Расписание по классам")

    # Выбор класса
    class_names = sorted(loader.classes.keys())
    selected_class = st.selectbox("Выберите класс:", class_names)

    if selected_class:
        # Получаем уроки класса
        class_lessons = [l for l in schedule.lessons
                        if selected_class in l.class_or_group]

        # Строим таблицу расписания
        df = build_schedule_table(class_lessons)
        st.dataframe(df, use_container_width=True, height=400)

        # Статистика класса
        st.markdown("---")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Всего уроков", len(class_lessons))

        with col2:
            gaps = schedule.get_class_gaps(selected_class)
            st.metric("Окон", gaps)

        with col3:
            ege = sum(1 for l in class_lessons if l.is_ege_practice)
            st.metric("Практикумов ЕГЭ", ege)


def show_by_teacher(schedule: Schedule, loader):
    """Показать расписание по учителям"""
    st.header("👨‍🏫 Расписание по учителям")

    # Выбор учителя
    teacher_names = sorted(loader.teachers.keys())
    selected_teacher = st.selectbox("Выберите учителя:", teacher_names)

    if selected_teacher:
        teacher = loader.teachers[selected_teacher]

        # Получаем уроки учителя
        teacher_lessons = schedule.get_lessons_by_teacher(selected_teacher)

        # Строим таблицу расписания
        df = build_schedule_table(teacher_lessons, show_class=True)
        st.dataframe(df, use_container_width=True, height=400)

        # Статистика учителя
        st.markdown("---")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Всего уроков", len(teacher_lessons))

        with col2:
            gaps = schedule.get_teacher_gaps(teacher)
            st.metric("Окон", gaps)

        with col3:
            unavailable = len(teacher.unavailable_days)
            st.metric("Недоступных дней", unavailable)


def show_by_classroom(schedule: Schedule, loader):
    """Показать загрузку кабинетов"""
    st.header("🏫 Загрузка кабинетов")

    # Таблица загрузки
    classroom_data = []

    for room_num, classroom in sorted(loader.classrooms.items()):
        lessons = [l for l in schedule.lessons
                  if l.classroom and l.classroom.number == room_num]

        load_pct = len(lessons) / 35 * 100  # 35 слотов в неделю

        classroom_data.append({
            "Кабинет": room_num,
            "Вместимость": classroom.capacity,
            "Этаж": classroom.floor,
            "Уроков": len(lessons),
            "Загрузка %": f"{load_pct:.1f}%"
        })

    df = pd.DataFrame(classroom_data)
    st.dataframe(df, use_container_width=True)


def show_export(schedule: Schedule, loader):
    """Экспорт расписания"""
    st.header("📥 Экспорт расписания")

    col1, col2 = st.columns(2)

    with col1:
        # Экспорт в JSON
        st.subheader("📄 JSON")

        json_data = json.dumps(schedule.to_dict(), ensure_ascii=False, indent=2)
        st.download_button(
            label="⬇️ Скачать JSON",
            data=json_data,
            file_name="schedule.json",
            mime="application/json"
        )

    with col2:
        # Экспорт в Excel
        st.subheader("📊 Excel")

        if st.button("📥 Подготовить Excel"):
            excel_data = export_to_excel(schedule, loader)
            st.download_button(
                label="⬇️ Скачать Excel",
                data=excel_data,
                file_name="schedule.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )


def build_schedule_table(lessons, show_class=False):
    """Построить таблицу расписания"""
    day_names = {
        DayOfWeek.MONDAY: "ПН",
        DayOfWeek.TUESDAY: "ВТ",
        DayOfWeek.WEDNESDAY: "СР",
        DayOfWeek.THURSDAY: "ЧТ",
        DayOfWeek.FRIDAY: "ПТ"
    }

    # Инициализируем таблицу
    data = {day_names[day]: [""] * 7 for day in DayOfWeek}
    data["Урок"] = list(range(1, 8))

    # Заполняем уроками
    for lesson in lessons:
        day_col = day_names[lesson.time_slot.day]
        row = lesson.time_slot.lesson_number - 1

        if show_class:
            cell = f"{lesson.subject}\n({lesson.class_or_group})"
        else:
            cell = f"{lesson.subject}\n{lesson.teacher.name}"

        if lesson.classroom:
            cell += f"\nкаб. {lesson.classroom.number}"

        # Если ячейка уже занята, добавляем
        if data[day_col][row]:
            data[day_col][row] += "\n---\n" + cell
        else:
            data[day_col][row] = cell

    df = pd.DataFrame(data)
    df = df[["Урок", "ПН", "ВТ", "СР", "ЧТ", "ПТ"]]

    return df


def export_to_excel(schedule: Schedule, loader) -> bytes:
    """Экспорт расписания в Excel"""
    output = BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Общий лист
        all_lessons = []
        for lesson in schedule.lessons:
            all_lessons.append({
                "День": lesson.time_slot.day.name,
                "Урок": lesson.time_slot.lesson_number,
                "Предмет": lesson.subject,
                "Учитель": lesson.teacher.name,
                "Класс/Группа": lesson.class_or_group,
                "Кабинет": lesson.classroom.number if lesson.classroom else "",
                "Практикум ЕГЭ": "Да" if lesson.is_ege_practice else "Нет"
            })

        df = pd.DataFrame(all_lessons)
        df.to_excel(writer, sheet_name="Все уроки", index=False)

        # Листы по классам
        for class_name in sorted(loader.classes.keys()):
            class_lessons = [l for l in schedule.lessons if class_name in l.class_or_group]
            df = build_schedule_table(class_lessons)
            df.to_excel(writer, sheet_name=class_name[:31], index=False)

    return output.getvalue()


if __name__ == "__main__":
    main()
