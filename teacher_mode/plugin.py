"""
Плагин режима учителя.
"""

import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

from core.plugin_base import BotPlugin
from .handlers import teacher_handlers, student_handlers
from .states import TeacherStates, StudentStates

logger = logging.getLogger(__name__)


class TeacherModePlugin(BotPlugin):
    """Плагин режима учителя"""

    code = "teacher_mode"
    title = "👨‍🏫 Режим учителя"
    menu_priority = 5  # Высокий приоритет

    async def post_init(self, app: Application):
        """Инициализация плагина"""
        logger.info("Teacher mode plugin initialized")

    def entry_handler(self):
        """Возвращает обработчик для входа из главного меню"""
        return CallbackQueryHandler(
            teacher_handlers.teacher_menu,
            pattern=f"^choose_{self.code}$"
        )

    def register(self, app: Application):
        """Регистрация обработчиков"""

        # ConversationHandler для учителей
        teacher_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                CallbackQueryHandler(teacher_handlers.teacher_menu, pattern=f"^choose_{self.code}$"),
            ],
            states={
                TeacherStates.TEACHER_MENU: [
                    # Основные пункты меню
                    CallbackQueryHandler(teacher_handlers.teacher_profile, pattern="^teacher_profile$"),
                    CallbackQueryHandler(teacher_handlers.show_teacher_subscriptions, pattern="^teacher_subscriptions$"),
                    CallbackQueryHandler(teacher_handlers.show_teacher_plan_details, pattern="^buy_teacher_"),

                    # Ученики и статистика
                    CallbackQueryHandler(teacher_handlers.show_student_list, pattern="^teacher_students$"),
                    CallbackQueryHandler(teacher_handlers.show_teacher_statistics, pattern="^teacher_statistics$"),
                    CallbackQueryHandler(teacher_handlers.show_teacher_assignments, pattern="^teacher_my_assignments$"),
                    CallbackQueryHandler(teacher_handlers.show_homework_stats, pattern="^homework_stats_"),

                    # Подарки и промокоды
                    CallbackQueryHandler(teacher_handlers.show_gift_subscription_menu, pattern="^teacher_gift_menu$"),
                    CallbackQueryHandler(teacher_handlers.show_promo_codes_list, pattern="^gift_my_promos$"),
                    CallbackQueryHandler(teacher_handlers.start_create_promo_code, pattern="^gift_create_promo$"),
                    CallbackQueryHandler(teacher_handlers.set_promo_duration, pattern="^promo_duration_"),
                    CallbackQueryHandler(teacher_handlers.create_promo_code_handler, pattern="^promo_uses_"),

                    # Создание задания
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),

                    # Навигация
                    CallbackQueryHandler(teacher_handlers.back_to_personal_cabinet, pattern="^back_to_cabinet$"),
                ],
                TeacherStates.CREATE_ASSIGNMENT: [
                    # Выбор типа задания
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),

                    # Выбор учеников
                    CallbackQueryHandler(teacher_handlers.toggle_student_selection, pattern="^toggle_student_"),

                    # Установка дедлайна
                    CallbackQueryHandler(teacher_handlers.set_assignment_deadline, pattern="^assignment_set_deadline$"),

                    # Создание задания
                    CallbackQueryHandler(teacher_handlers.confirm_and_create_assignment, pattern="^deadline_"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.SELECT_SELECTION_MODE: [
                    # Выбор способа отбора заданий
                    CallbackQueryHandler(teacher_handlers.select_selection_mode, pattern="^selection_mode_"),

                    # Назад к выбору типа задания
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.SELECT_TOPICS: [
                    # Переключение выбора блоков
                    CallbackQueryHandler(teacher_handlers.toggle_block_selection, pattern="^toggle_block:"),

                    # Подтверждение выбора блоков
                    CallbackQueryHandler(teacher_handlers.confirm_topic_blocks, pattern="^topics_confirm_blocks$"),

                    # Назад к выбору типа задания
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.SELECT_SPECIFIC_QUESTIONS: [
                    # Переключение выбора конкретного задания
                    CallbackQueryHandler(teacher_handlers.toggle_question_selection, pattern="^toggle_question:"),

                    # Выбор/снятие всех заданий
                    CallbackQueryHandler(teacher_handlers.select_all_questions, pattern="^select_all_questions$"),
                    CallbackQueryHandler(teacher_handlers.deselect_all_questions, pattern="^deselect_all_questions$"),

                    # Подтверждение выбора заданий
                    CallbackQueryHandler(teacher_handlers.confirm_selected_questions, pattern="^confirm_selected_questions$"),

                    # Назад к выбору типа задания
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTER_QUESTION_NUMBERS: [
                    # Обработка текстового ввода номеров заданий
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_question_numbers_input),

                    # Подтверждение выбранных номеров
                    CallbackQueryHandler(teacher_handlers.confirm_numbers_selection, pattern="^confirm_numbers_selection$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
            ],
            name="teacher_conversation",
            persistent=False,
            allow_reentry=True,
        )

        # ConversationHandler для учеников (подключение к учителю)
        student_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(student_handlers.enter_teacher_code_start, pattern="^connect_to_teacher$"),
            ],
            states={
                StudentStates.ENTER_TEACHER_CODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, student_handlers.process_teacher_code),
                    CallbackQueryHandler(student_handlers.cancel_connection, pattern="^main_menu$"),
                ],
                StudentStates.CONFIRM_TEACHER: [
                    CallbackQueryHandler(student_handlers.confirm_teacher_connection, pattern="^confirm_teacher_connection$"),
                    CallbackQueryHandler(student_handlers.cancel_connection, pattern="^main_menu$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(student_handlers.cancel_connection, pattern="^main_menu$"),
            ],
            name="student_connect_conversation",
            persistent=False,
            allow_reentry=True,
        )

        # Обработчики для работы с ДЗ ученика
        app.add_handler(CallbackQueryHandler(student_handlers.homework_list, pattern="^student_homework_list$"))
        app.add_handler(CallbackQueryHandler(student_handlers.view_homework, pattern="^homework_\\d+$"))
        app.add_handler(CallbackQueryHandler(student_handlers.start_homework, pattern="^start_homework_\\d+$"))

        # Регистрация ConversationHandler'ов
        app.add_handler(teacher_conv_handler)
        app.add_handler(student_conv_handler)

        logger.info("Teacher mode plugin handlers registered")


# Экспорт экземпляра плагина
plugin = TeacherModePlugin()
