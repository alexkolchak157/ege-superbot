from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import logging

from . import db
from . import utils
from . import keyboards
from .config import REQUIRED_CHANNEL
from .states import QuizState

async def start_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = keyboards.get_main_menu_keyboard()
    await update.message.reply_text(
        "👋 Добро пожаловать! Что вы хотите потренировать?",
        reply_markup=kb
    )
    return QuizState.CHOOSING_MAIN_SECTION

async def choose_section(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "choose_test_part":
        kb = keyboards.get_initial_choice_keyboard()
        await query.message.edit_text("Выберите режим:", reply_markup=kb)
        return QuizState.CHOOSING_INITIAL_ACTION
    elif query.data == "choose_task24":
        await query.message.edit_text("Перехожу к модулю 24 (План)!")


async def cmd_reminders_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        db.set_reminders_status(user_id, False)
        await context.bot.send_message(
            user_id,
            "Хорошо, я больше не буду присылать напоминания о тренировках."
        )
    except Exception:
        logging.exception("Ошибка при отключении напоминаний")
        await context.bot.send_message(
            user_id,
            "Не удалось обновить настройки напоминаний."
        )

# ─── Команда /reminders_on ──────────────────────────────────────────────
async def cmd_reminders_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        db.set_reminders_status(user_id, True)
        await update.message.reply_text(
            "Отлично! Я буду напоминать вам о тренировках, если вы долго не будете заходить."
        )
    except Exception:
        logging.exception(f"Ошибка включения напоминаний для user {user_id}")
        await update.message.reply_text(
            "Не удалось обновить настройки напоминаний."
        )

# ─── Команда /start (с проверкой подписки) ──────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user

    if not await utils.check_subscription(user.id, context.bot):
        subscribe_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Подписаться на канал",
                    url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Я подписался, проверить!",
                    callback_data="check_subscription"
                )
            ],
        ])
        await update.message.reply_text(
            f"Привет, {user.first_name}! Для доступа — подпишитесь на {REQUIRED_CHANNEL}.",
            reply_markup=subscribe_kb
        )
        return

    kb = keyboards.get_initial_choice_keyboard()
    await update.message.reply_text(
        f"Привет, {user.first_name}! Выберите, с чего начнём:",
        reply_markup=kb
    )
    return QuizState.CHOOSING_INITIAL_ACTION

# ─── Колбэк «Я подписался, проверить» ────────────────────────────────────
async def cq_check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if await utils.check_subscription(user.id, context.bot):
        try:
            await query.message.delete()
        except Exception:
            logging.warning("Не удалось удалить сообщение с кнопкой подписки")

        kb = keyboards.get_initial_choice_keyboard()
        await context.bot.send_message(
            update.effective_chat.id,
            f"Отлично, {user.first_name}! Теперь вы можете пользоваться всеми функциями.\n\n"
            "Выберите, с чего начнём:",
            reply_markup=kb
        )
        return QuizState.CHOOSING_INITIAL_ACTION
    else:
        await query.answer(
            "Подписка не найдена. Пожалуйста, подпишитесь на канал и попробуйте снова.",
            show_alert=True
        )

# ─── Команда /cancel ────────────────────────────────────────────────────
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Завершаем текущее действие и возвращаемся в главное меню
    kb = keyboards.get_initial_choice_keyboard()
    if update.message:
        await update.message.reply_text(
            "Текущее действие отменено. Выберите режим:",
            reply_markup=kb
        )
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.message.edit_text(
            "Текущее действие отменено. Выберите режим:",
            reply_markup=kb
        )
    return QuizState.CHOOSING_INITIAL_ACTION

# ─── Выбор номера ЕГЭ ────────────────────────────────────────────────────
async def cq_initial_select_exam_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not await utils.check_subscription(user.id, context.bot):
        await query.answer(f"Сначала подпишитесь на {REQUIRED_CHANNEL}", show_alert=True)
        return

    # Собираем все номера ЕГЭ из базы вопросов
    all_nums = set()
    for block in utils.QUESTIONS_DATA.values():
        for topic_qs in block.values():
            for q in topic_qs:
                num = q.get("exam_number")
                if isinstance(num, int):
                    all_nums.add(num)

    if not all_nums:
        await query.answer("В базе нет вопросов с номерами ЕГЭ.", show_alert=True)
        return

    kb = keyboards.get_exam_number_keyboard(sorted(all_nums))
    try:
        await query.message.edit_text(
            "Выберите номер задания ЕГЭ:", reply_markup=kb
        )
        return QuizState.CHOOSING_EXAM_NUMBER
    except Exception as e:
        logging.error(f"Error editing for exam number: {e}")
        await query.answer("Ошибка отображения клавиатуры.")

# ─── Выбор блока тем ────────────────────────────────────────────────────
async def cq_initial_select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not await utils.check_subscription(user.id, context.bot):
        await query.answer(f"Сначала подпишитесь на {REQUIRED_CHANNEL}", show_alert=True)
        return

    kb = keyboards.get_blocks_keyboard(utils.AVAILABLE_BLOCKS)
    if not kb:
        await query.answer("В базе нет доступных блоков.", show_alert=True)
        return

    try:
        await query.message.edit_text(
            "Выберите блок тем для начала:", reply_markup=kb
        )
        return QuizState.CHOOSING_BLOCK
    except Exception as e:
        logging.error(f"Error editing for block selection: {e}")
        await query.answer("Ошибка отображения клавиатуры.")

# ─── Случайный вопрос из всей базы ──────────────────────────────────────
async def cq_initial_select_random_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not await utils.check_subscription(user.id, context.bot):
        await query.answer(f"Сначала подпишитесь на {REQUIRED_CHANNEL}", show_alert=True)
        return

    all_qs = []
    for block in utils.QUESTIONS_DATA.values():
        for topic_qs in block.values():
            all_qs.extend(topic_qs)

    if not all_qs:
        await query.answer("В базе нет вопросов!", show_alert=True)
        return

    try:
        await query.message.edit_text("⏳ Загружаю случайный вопрос...", reply_markup=None)
        qd = await utils.choose_question(user.id, all_qs)
        if not qd:
            kb = keyboards.get_initial_choice_keyboard()
            await context.bot.send_message(
                update.effective_chat.id,
                "Вы ответили на все доступные вопросы! 🎉\n\nМожет, начнём сначала?",
                reply_markup=kb
            )
            return QuizState.CHOOSING_INITIAL_ACTION

        # отправляем вопрос (функция utils.send_question должна быть адаптирована под PTB)
        await utils.send_question(update, context, qd, last_mode="random_all")
        return QuizState.ANSWERING

    except Exception as e:
        logging.exception(f"Error in random_all: {e}")
        await query.answer("Ошибка при выборе случайного вопроса.", show_alert=True)

# ─── Кнопка «Назад» из блока ─────────────────────────────────────────────
async def cq_block_back_to_initial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = keyboards.get_initial_choice_keyboard()
    try:
        await query.message.edit_text("Выберите режим:", reply_markup=kb)
        return QuizState.CHOOSING_INITIAL_ACTION
    except Exception as e:
        logging.error(f"Error back to initial from block: {e}")
        await query.answer("Произошла ошибка.")

# ─── Кнопка «Назад» из номера ЕГЭ ────────────────────────────────────────
async def cq_exam_num_back_to_initial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = keyboards.get_initial_choice_keyboard()
    try:
        await query.message.edit_text("Выберите режим:", reply_markup=kb)
        return QuizState.CHOOSING_INITIAL_ACTION
    except Exception as e:
        logging.error(f"Error back to initial from exam_num: {e}")
        await query.answer("Произошла ошибка.")
async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        stats_raw = db.get_user_stats(user_id)
        mistake_ids = db.get_mistake_ids(user_id)
        streaks = db.get_user_streaks(user_id)

        # Формируем текст с учётом двух стриков и ошибок…
        text = utils.build_score_text(stats_raw, mistake_ids, streaks)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logging.exception(f"Ошибка при получении статистики для user {user_id}: {e}")
        await update.message.reply_text("Не удалось получить статистику. Попробуйте позже.")

# ─── Обработчики неожиданных действий ──────────────────────────────────
async def handle_unexpected_initial_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = keyboards.get_initial_choice_keyboard()
    await update.message.reply_text(
        "Пожалуйста, используйте кнопки для выбора режима.",
        reply_markup=kb
    )

async def handle_unexpected_block_choice_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = keyboards.get_blocks_keyboard(utils.AVAILABLE_BLOCKS)
    await update.message.reply_text(
        "Пожалуйста, выберите блок с помощью кнопок.",
        reply_markup=kb
    )

async def handle_unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я не понимаю эту команду. Используйте /start, чтобы начать."
    )

# --- ConversationHandler для тестовой части ---
def register_test_handlers(app):
    conv_handler = ConversationHandler(
    entry_points=[],
        states={
            QuizState.CHOOSING_INITIAL_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unexpected_initial_choice),
                CallbackQueryHandler(cq_initial_select_exam_num, pattern="^initial:select_exam_num_mode$"),
                CallbackQueryHandler(cq_initial_select_block, pattern="^initial:select_block_mode$"),
                CallbackQueryHandler(cq_initial_select_random_all, pattern="^initial:select_random_all$"),
                CallbackQueryHandler(cq_check_subscription, pattern="^check_subscription$"),
            ],
            QuizState.CHOOSING_BLOCK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unexpected_block_choice_msg),
                CallbackQueryHandler(cq_block_back_to_initial, pattern="^block:back_to_initial$"),
            ],
            QuizState.CHOOSING_EXAM_NUMBER: [
                CallbackQueryHandler(cq_exam_num_back_to_initial, pattern="^exam_number:back_to_initial$"),
                # Добавь свои хендлеры для выбора номера ЕГЭ
            ],
            # Добавь другие состояния по необходимости
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
        ],
        allow_reentry=True,  # опционально
    )
    app.add_handler(conv_handler)

    # --- Общие хендлеры вне ConversationHandler ---
    app.add_handler(CommandHandler("reminders_off", cmd_reminders_off))
    app.add_handler(CommandHandler("reminders_on", cmd_reminders_on))
    app.add_handler(CommandHandler("score", cmd_score))

    # Фолбек на любые неизвестные текстовые сообщения (в самом конце!)
    app.add_handler(MessageHandler(filters.TEXT, handle_unknown_command))
