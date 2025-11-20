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

                    # Обработчики оплаты подписки (используем обработчики из payment)
                    CallbackQueryHandler(teacher_handlers.handle_teacher_subscription_payment, pattern="^pay_teacher_"),
                    CallbackQueryHandler(teacher_handlers.handle_payment_callback, pattern="^confirm_teacher_plan:"),
                    CallbackQueryHandler(teacher_handlers.handle_payment_callback, pattern="^duration_"),

                    # Ученики и статистика
                    CallbackQueryHandler(teacher_handlers.show_student_list, pattern="^teacher_students$"),
                    CallbackQueryHandler(teacher_handlers.show_teacher_statistics, pattern="^teacher_statistics$"),
                    CallbackQueryHandler(teacher_handlers.show_teacher_assignments, pattern="^teacher_my_assignments$"),
                    CallbackQueryHandler(teacher_handlers.show_homework_stats, pattern="^homework_stats_"),

                    # Просмотр ответов учеников
                    CallbackQueryHandler(teacher_handlers.view_homework_submissions, pattern="^homework_submissions:"),
                    CallbackQueryHandler(teacher_handlers.view_student_progress, pattern="^view_student_progress:"),
                    CallbackQueryHandler(teacher_handlers.view_answer_detail, pattern="^view_answer:"),
                    CallbackQueryHandler(teacher_handlers.initiate_comment_entry, pattern="^add_comment:"),
                    CallbackQueryHandler(teacher_handlers.initiate_score_override, pattern="^override_score:"),

                    # Статистика ученика
                    CallbackQueryHandler(teacher_handlers.show_student_statistics, pattern="^student_stats:"),

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

                    # Ввод названия задания
                    CallbackQueryHandler(teacher_handlers.prompt_assignment_title, pattern="^assignment_enter_title$"),

                    # Установка дедлайна
                    CallbackQueryHandler(teacher_handlers.set_assignment_deadline, pattern="^assignment_set_deadline$"),

                    # Создание задания
                    CallbackQueryHandler(teacher_handlers.confirm_and_create_assignment, pattern="^deadline_"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTER_ASSIGNMENT_TITLE: [
                    # Обработка текстового ввода названия задания
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_assignment_title_input),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.SELECT_SELECTION_MODE: [
                    # Выбор способа отбора заданий
                    CallbackQueryHandler(teacher_handlers.select_selection_mode, pattern="^selection_mode_"),

                    # Смешанное задание
                    CallbackQueryHandler(teacher_handlers.toggle_mixed_module_selection, pattern="^toggle_mixed_module:"),
                    CallbackQueryHandler(teacher_handlers.proceed_with_mixed_selection, pattern="^proceed_mixed_selection$"),

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
                    CallbackQueryHandler(teacher_handlers.confirm_exam_numbers_selection, pattern="^confirm_exam_numbers_selection$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTER_QUESTION_COUNT: [
                    # Обработка текстового ввода количества заданий для режима "все"
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_question_count_input),

                    # Подтверждение сгенерированных заданий
                    CallbackQueryHandler(teacher_handlers.confirm_all_tasks_selection, pattern="^confirm_all_tasks_selection$"),
                    CallbackQueryHandler(teacher_handlers.confirm_mixed_selection, pattern="^confirm_mixed_selection$"),

                    # Перегенерация
                    CallbackQueryHandler(teacher_handlers.regenerate_all_tasks, pattern="^regenerate_all_tasks$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTERING_COMMENT: [
                    # Обработка текстового ввода комментария
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_teacher_comment),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.cancel_comment_entry, pattern="^cancel_comment:"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.OVERRIDING_SCORE: [
                    # Обработка кнопок принятия/отклонения ответа
                    CallbackQueryHandler(teacher_handlers.process_score_override, pattern="^set_score_accept:"),
                    CallbackQueryHandler(teacher_handlers.process_score_override, pattern="^set_score_reject:"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.view_answer_detail, pattern="^view_answer:"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTER_CUSTOM_QUESTION: [
                    # Обработка текстового ввода кастомного вопроса
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_custom_question),

                    # Кнопки управления
                    CallbackQueryHandler(teacher_handlers.finish_custom_questions, pattern="^finish_custom_questions$"),
                    CallbackQueryHandler(teacher_handlers.review_custom_questions, pattern="^review_custom_questions$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.REVIEW_CUSTOM_QUESTIONS: [
                    # Кнопки управления списком вопросов
                    CallbackQueryHandler(teacher_handlers.add_more_custom_questions, pattern="^add_more_custom_questions$"),
                    CallbackQueryHandler(teacher_handlers.finish_custom_questions, pattern="^finish_custom_questions$"),
                    CallbackQueryHandler(teacher_handlers.delete_last_custom_question, pattern="^delete_last_custom_question$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.PAYMENT_ENTERING_PROMO: [
                    # Обработка ввода промокода
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.handle_promo_input),

                    # Пропуск промокода
                    CallbackQueryHandler(teacher_handlers.handle_skip_promo, pattern="^skip_promo$"),

                    # Навигация назад к выбору длительности
                    CallbackQueryHandler(teacher_handlers.handle_back_to_duration, pattern="^back_to_duration_selection$"),

                    # Отмена платежа
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^cancel_payment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.PAYMENT_ENTERING_EMAIL: [
                    # Обработка ввода email для оплаты
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.handle_payment_email_input),

                    # Отмена платежа
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^cancel_payment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.PAYMENT_AUTO_RENEWAL_CHOICE: [
                    # Обработка выбора типа оплаты (автопродление или разовая)
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^choose_auto_renewal$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^choose_no_auto_renewal$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^show_auto_renewal_terms$"),

                    # Дополнительные обработчики для экрана согласия
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^toggle_consent_checkbox$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^confirm_with_auto_renewal$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^need_consent_reminder$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^show_user_agreement$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^back_to_payment_choice$"),

                    # Навигация назад к длительности
                    CallbackQueryHandler(teacher_handlers.handle_back_to_duration, pattern="^back_to_duration$"),

                    # Отмена платежа
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^cancel_payment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
            ],
            name="teacher_conversation",
            persistent=True,
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
            persistent=True,
            allow_reentry=True,
        )

        # ConversationHandler для выполнения домашних заданий
        homework_execution_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(student_handlers.show_homework_question, pattern="^hw_question:"),
            ],
            states={
                StudentStates.DOING_HOMEWORK: [
                    # Прием ответа от ученика
                    MessageHandler(filters.TEXT & ~filters.COMMAND, student_handlers.process_homework_answer),

                    # Возврат к списку вопросов
                    CallbackQueryHandler(student_handlers.start_homework, pattern="^start_homework_\\d+$"),

                    # Возврат в главное меню
                    CallbackQueryHandler(student_handlers.cancel_homework_execution, pattern="^main_menu$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(student_handlers.cancel_homework_execution, pattern="^main_menu$"),
            ],
            name="homework_execution",
            persistent=True,
            allow_reentry=True,
        )

        # Обработчики для работы с ДЗ ученика (вне conversation)
        app.add_handler(CallbackQueryHandler(student_handlers.homework_list, pattern="^student_homework_list$"))
        app.add_handler(CallbackQueryHandler(student_handlers.view_homework, pattern="^homework_\\d+$"))
        app.add_handler(CallbackQueryHandler(student_handlers.start_homework, pattern="^start_homework_\\d+$"))

        # Обработчики для работы с платежами (вне conversation)
        app.add_handler(CallbackQueryHandler(teacher_handlers.handle_check_payment, pattern="^check_payment$"))
        app.add_handler(CallbackQueryHandler(teacher_handlers.handle_cancel_payment, pattern="^cancel_payment$"))

        # Регистрация ConversationHandler'ов
        # ВАЖНО: Используем group=-40 чтобы teacher conversation обрабатывался
        # ПОСЛЕ payment conversation (group=-50), но с более высоким приоритетом чем обычные handlers (group=0)
        # Это предотвращает конфликты: payment ConversationHandler проверяется первым,
        # но если пользователь уже в teacher conversation, то teacher handlers будут обрабатывать callbacks
        app.add_handler(teacher_conv_handler, group=-40)
        app.add_handler(student_conv_handler, group=-40)
        app.add_handler(homework_execution_handler, group=-40)

        logger.info("Teacher mode plugin handlers registered (group=-40)")


# Экспорт экземпляра плагина
plugin = TeacherModePlugin()
