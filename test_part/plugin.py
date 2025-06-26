# test_part/plugin.py
import logging
from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers
from .missing_handlers import (
    detailed_report,
    export_csv,
    work_mistakes,
    check_subscription,
    test_start_mistakes
)

logger = logging.getLogger(__name__)

class TestPartPlugin(BotPlugin):
    code = "test_part"
    title = "Тестовая часть"
    menu_priority = 10
    
    def __init__(self):
        super().__init__()
        self._initialized = False
    
    async def post_init(self, app):
        """Загрузка данных при старте с улучшенной обработкой ошибок."""
        try:
            # Импортируем и загружаем вопросы
            from .loader import load_questions
            
            logger.info(f"Loading questions for {self.title} plugin...")
            questions_data, questions_list = load_questions()
            
            if questions_data and questions_list:
                # Инициализируем данные в handlers
                handlers.init_data()
                
                # Подсчитываем статистику
                total_questions = len(questions_list)
                total_blocks = len(questions_data)
                total_topics = sum(len(topics) for topics in questions_data.values())
                
                logger.info(
                    f"{self.title} plugin initialized successfully: "
                    f"{total_questions} questions, {total_blocks} blocks, {total_topics} topics"
                )
                
                # Проверяем доступность кеша
                try:
                    from .cache import questions_cache
                    if questions_cache and questions_cache._is_built:
                        logger.info("Questions cache is available and built")
                    else:
                        logger.info("Questions cache not available, using fallback methods")
                except ImportError:
                    logger.info("Cache module not found, using fallback methods")
                
                self._initialized = True
                
            else:
                logger.error(f"Failed to load questions for {self.title} plugin")
                self._initialized = False
                
        except Exception as e:
            logger.error(f"Error initializing {self.title} plugin: {e}")
            self._initialized = False
    
    def is_initialized(self) -> bool:
        """Проверяет, инициализирован ли плагин."""
        return self._initialized
    
    def register(self, app):
        """Регистрация обработчиков с улучшенной структурой."""
        
        # Основной ConversationHandler для тестовой части
        main_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    handlers.entry_from_menu,
                    pattern=f"^choose_{self.code}$"
                ),
                CommandHandler("quiz", handlers.cmd_quiz),
                CommandHandler("start_quiz", handlers.cmd_quiz),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Режимы из главного меню
                    CallbackQueryHandler(
                        handlers.select_exam_num_mode, 
                        pattern="^initial:select_exam_num$"
                    ),
                    CallbackQueryHandler(
                        handlers.select_block_mode, 
                        pattern="^initial:select_block$"
                    ),
                    CallbackQueryHandler(
                        handlers.select_random_all, 
                        pattern="^initial:select_random_all$"
                    ),
                    CallbackQueryHandler(
                        handlers.select_mistakes, 
                        pattern="^initial:select_mistakes$"
                    ),
                    CallbackQueryHandler(
                        handlers.select_practice_mode,
                        pattern="^test_part_practice$"
                    ),
                    CallbackQueryHandler(
                        handlers.select_mistakes,
                        pattern="^test_part_mistakes$"
                    ),
                    CallbackQueryHandler(
                        handlers.detailed_report,
                        pattern="^test_part_progress$"
                    ),
                    CallbackQueryHandler(
                        handlers.reset_progress_confirm,
                        pattern="^test_part_reset_confirm$"
                    ),
                    CallbackQueryHandler(
                        handlers.reset_progress_do,
                        pattern="^test_part_reset_do$"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_test_menu,
                        pattern="^to_test_part_menu$"
                    ),
                    
                    # Режимы внутри блока
                    CallbackQueryHandler(
                        handlers.select_mode_random_in_block, 
                        pattern="^mode:random$"
                    ),
                    CallbackQueryHandler(
                        handlers.select_mode_topic_in_block, 
                        pattern="^mode:choose_topic$"
                    ),
                    
                    # Навигация назад
                    CallbackQueryHandler(
                        handlers.back_to_mode, 
                        pattern="^to_test_part_menu$"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_mode, 
                        pattern="^to_blocks$"
                    ),
                    
                    # Дополнительные обработчики из missing_handlers
                    CallbackQueryHandler(
                        detailed_report,
                        pattern="^detailed_report$"
                    ),
                    CallbackQueryHandler(
                        export_csv,
                        pattern="^export_csv$"
                    ),
                    CallbackQueryHandler(
                        work_mistakes,
                        pattern="^work_mistakes$"
                    ),
                    CallbackQueryHandler(
                        check_subscription,
                        pattern="^check_subscription$"
                    ),
                    CallbackQueryHandler(
                        test_start_mistakes,
                        pattern="^test_start_mistakes$"
                    ),
                    
                    # Возврат в главное меню
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                    CallbackQueryHandler(
                        handlers.handle_unknown_callback,
                        pattern=".*"
                    ),
                ],
                
                states.CHOOSING_TOPIC: [
                    CallbackQueryHandler(
                        handlers.select_topic, 
                        pattern=r"^topic:"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_mode, 
                        pattern="^to_mode$"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_mode, 
                        pattern="^to_test_part_menu$"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                ],
                
                states.CHOOSING_BLOCK: [
                    CallbackQueryHandler(
                        handlers.select_block, 
                        pattern=r"^block:select:"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_mode, 
                        pattern="^block:back_to_initial$"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                ],
                
                states.CHOOSING_EXAM_NUMBER: [
                    CallbackQueryHandler(
                        handlers.select_exam_num, 
                        pattern=r"^exam_number:select:"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_mode, 
                        pattern="^exam_number:back_to_initial$"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                ],
                
                states.ANSWERING: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,  # Убрали & filters.create(...)
                        handlers.check_answer
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                ],
                
                states.CHOOSING_NEXT_ACTION: [
                    CallbackQueryHandler(
                        handlers.handle_next_action,
                        pattern="^test_next_"
                    ),
                    CallbackQueryHandler(
                        handlers.handle_next_action,
                        pattern="^test_mistake_"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                ],
                
                states.REVIEWING_MISTAKES: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, 
                        handlers.handle_mistake_answer
                    ),
                    CallbackQueryHandler(
                        handlers.mistake_nav,
                        pattern="^test_mistake_"
                    ),
                    CallbackQueryHandler(
                        handlers.handle_next_action,
                        pattern="^test_next_"
                    ),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(
                    handlers.back_to_main_menu,
                    pattern="^to_main_menu$"
                ),
                # Добавляем обработчик для всех callback_data, которые не подходят под другие паттерны
                CallbackQueryHandler(
                    handlers.handle_unknown_callback,
                    pattern="^(?!choose_test_part|initial:|block:|topic:|exam_number:|mode:|test_).*$"
                ),
            ],
            allow_reentry=True,
            name=f"{self.code}_main_conversation",
            persistent=False,
        )
        
        # Отдельные команды вне ConversationHandler
        app.add_handler(CommandHandler("mistakes", handlers.cmd_mistakes))
        app.add_handler(CommandHandler("score", handlers.cmd_score))
        
        # Регистрируем основной ConversationHandler
        app.add_handler(main_conv_handler)
        
        logger.info(f"TestPart plugin registered successfully")
    
    async def _handle_to_main_menu(self, update, context):
        """Вспомогательный метод для обработки возврата в главное меню."""
        from core.plugin_loader import build_main_menu
        
        try:
            kb = build_main_menu()
            
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    "👋 Что хотите потренировать?",
                    reply_markup=kb
                )
            else:
                await update.message.reply_text(
                    "👋 Что хотите потренировать?",
                    reply_markup=kb
                )
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error in _handle_to_main_menu: {e}")
            
            if update.callback_query:
                await update.callback_query.answer("Возврат в главное меню...")
            
            return ConversationHandler.END
    
    def get_menu_button(self):
        """Возвращает кнопку для главного меню."""
        from telegram import InlineKeyboardButton
        return InlineKeyboardButton(
            text=self.title,
            callback_data=f"choose_{self.code}"
        )
    
    def get_status_info(self) -> dict:
        """Возвращает информацию о статусе плагина."""
        status = {
            "initialized": self._initialized,
            "code": self.code,
            "title": self.title,
            "questions_loaded": False,
            "cache_available": False,
            "total_questions": 0,
            "total_blocks": 0,
            "total_topics": 0
        }
        
        if self._initialized:
            try:
                from .loader import QUESTIONS_DATA, QUESTIONS_LIST_FLAT
                
                if QUESTIONS_DATA and QUESTIONS_LIST_FLAT:
                    status["questions_loaded"] = True
                    status["total_questions"] = len(QUESTIONS_LIST_FLAT)
                    status["total_blocks"] = len(QUESTIONS_DATA)
                    status["total_topics"] = sum(
                        len(topics) for topics in QUESTIONS_DATA.values()
                    )
                
                try:
                    from .cache import questions_cache
                    status["cache_available"] = (
                        questions_cache and questions_cache._is_built
                    )
                except ImportError:
                    pass
                    
            except Exception as e:
                logger.error(f"Error getting status info: {e}")
        
        return status

# Создаем экземпляр плагина
plugin = TestPartPlugin()