"""
Плагин режима учителя.
"""

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

from core.plugin_base import BotPlugin
from .handlers import teacher_handlers, student_handlers, assignment_handlers, analytics_handlers
from .states import TeacherStates, StudentStates


class TeacherModePlugin(BotPlugin):
    """Плагин режима учителя"""

    code = "teacher_mode"
    title = "👨‍🏫 Режим учителя"
    menu_priority = 5  # Высокий приоритет

    async def post_init(self, app: Application):
        """Инициализация плагина"""
        # TODO: Инициализация БД для режима учителя
        pass

    def register(self, app: Application):
        """Регистрация обработчиков"""

        # ConversationHandler для учителей
        teacher_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
            ],
            states={
                TeacherStates.TEACHER_MENU: [
                    CallbackQueryHandler(analytics_handlers.show_student_list, pattern="^teacher_students$"),
                    CallbackQueryHandler(assignment_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),
                    CallbackQueryHandler(analytics_handlers.show_statistics, pattern="^teacher_statistics$"),
                    CallbackQueryHandler(teacher_handlers.teacher_profile, pattern="^teacher_profile$"),
                ],
                TeacherStates.SELECT_ASSIGNMENT_TYPE: [
                    CallbackQueryHandler(assignment_handlers.select_module, pattern="^assign_existing$"),
                ],
                TeacherStates.SELECT_MODULE: [
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^create_assignment$"),
                ],
                TeacherStates.STUDENT_LIST: [
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.VIEW_STATISTICS: [
                    CallbackQueryHandler(analytics_handlers.show_student_list, pattern="^teacher_students$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
            ],
            name="teacher_conversation",
            persistent=False,
        )

        # ConversationHandler для учеников (подключение к учителю)
        student_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(student_handlers.enter_teacher_code_start, pattern="^connect_to_teacher$"),
            ],
            states={
                StudentStates.ENTER_TEACHER_CODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, student_handlers.process_teacher_code),
                ],
                StudentStates.CONFIRM_TEACHER: [
                    CallbackQueryHandler(student_handlers.homework_list, pattern="^confirm_teacher_"),
                ],
            },
            fallbacks=[],
            name="student_connect_conversation",
            persistent=False,
        )

        # Обработчик для списка ДЗ
        app.add_handler(CallbackQueryHandler(student_handlers.homework_list, pattern="^my_homeworks$"))

        # Регистрация ConversationHandler'ов
        app.add_handler(teacher_conv_handler)
        app.add_handler(student_conv_handler)


# Экспорт экземпляра плагина
plugin = TeacherModePlugin()
