from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers

class Task24Plugin(BotPlugin):
    code = "task24"
    title = "Задание 24 (План)"
    menu_priority = 20
    
    async def post_init(self, app):
        """Загрузка данных планов."""
        handlers.init_data()
    
    def register(self, app):
        """Регистрация обработчиков."""
        
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    handlers.entry_from_menu,
                    pattern=f"^choose_{self.code}$"
                ),
                CommandHandler("start_plan", handlers.cmd_start_plan),
            ],
            states={
                states.CHOOSING_MODE: [
                    CallbackQueryHandler(handlers.train_mode, pattern="^t24_train$"),
                    CallbackQueryHandler(handlers.show_mode, pattern="^t24_show$"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t24_show_list$"),
                    CallbackQueryHandler(handlers.exam_mode, pattern="^t24_exam$"),
                    CallbackQueryHandler(handlers.search_topics, pattern="^t24_search$"),
                    CallbackQueryHandler(handlers.show_criteria, pattern="^t24_criteria$"),
                    CallbackQueryHandler(handlers.show_help, pattern="^t24_help$"),
                    CallbackQueryHandler(handlers.reset_progress, pattern="^t24_reset$"),
                    CallbackQueryHandler(handlers.show_block_stats, pattern="^t24_progress$"),
                    CallbackQueryHandler(handlers.show_detailed_progress, pattern="^t24_detailed_progress$"),
                    CallbackQueryHandler(handlers.show_completed, pattern="^t24_completed$"),
                    CallbackQueryHandler(handlers.show_remaining, pattern="^t24_remaining$"),
                    CallbackQueryHandler(handlers.export_progress, pattern="^t24_export$"),
                    CallbackQueryHandler(handlers.retry_plan, pattern="^t24_retry_plan$"),
                    CallbackQueryHandler(handlers.back_to_choice_shortcut, pattern="^t24_back_to_choice$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.cancel_reset, pattern="^t24_cancel_reset$"),
                ],
                states.CHOOSING_TOPIC: [
                    CallbackQueryHandler(handlers.select_topic, pattern=r"^topic:"),
                    CallbackQueryHandler(handlers.navigate_topics, pattern=r"^nav:"),
                    CallbackQueryHandler(handlers.next_topic, pattern="^t24_next_topic$"),
                    CallbackQueryHandler(handlers.back_to_menu, pattern="^t24_back_main$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.noop, pattern="^noop$")
                ],
                states.AWAITING_PLAN: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_plan_enhanced),
                    MessageHandler(filters.Document.ALL, handlers.handle_plan_document),
                ],
                states.AWAITING_SEARCH: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_search_query),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.back_to_menu, pattern="^t24_menu$"),
            ],
            allow_reentry=True,
        )
        
        app.add_handler(conv_handler)
        app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer() if u.callback_query else None,pattern="^streak_ok$"))
        app.add_handler(CommandHandler("criteria", handlers.cmd_criteria))

plugin = Task24Plugin()