import os
import json
import logging

from .checker import PlanBotData, evaluate_plan, FEEDBACK_KB
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler,ConversationHandler,
    CallbackQueryHandler, MessageHandler, filters, ContextTypes
)


# ——————————————————————————————————————————————————————————
# Загрузка данных и инициализация
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TG_TOKEN") or os.getenv("PLANBOT_TOKEN")
PLANS_FILE = os.getenv("PLANS_FILE", "plans_data_with_blocks.json")
DATA = json.load(open(PLANS_FILE, encoding="utf-8"))
BOT_DATA = PlanBotData(DATA)

# ——————————————————————————————————————————————————————————
# Клавиатуры
MAIN_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("💪 Тренироваться", callback_data="start_train")],
    [InlineKeyboardButton("📜 Темы",           callback_data="start_list")],
    [InlineKeyboardButton("🚫 Выход",          callback_data="stop")]
])

# ——————————————————————————————————————————————————————————
# Команда /start
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выберите режим:", reply_markup=MAIN_KB)
    ctx.user_data.clear()

# ——————————————————————————————————————————————————————————
# Начало тренировки
async def start_train(update: Update, ctx):
    # отправляем список тем (по блокам или все сразу)
    kb = build_block_selection_keyboard("train")  # можно адаптировать из planbot.py :contentReference[oaicite:6]{index=6}:contentReference[oaicite:7]{index=7}
    await update.callback_query.message.edit_text("Выберите блок:", reply_markup=kb)

async def start_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показываем блоки тем для выбора (по аналогии с start_train)."""
    await update.callback_query.answer()
    kb = build_block_selection_keyboard("train")  # или "list", как вам удобнее
    await update.callback_query.message.edit_text(
        "Выберите блок:", reply_markup=kb
    )
# ——————————————————————————————————————————————————————————
# Обработчик темы
async def select_topic(update: Update, ctx):
    topic = update.callback_query.data.split(":")[-1]
    ctx.user_data["topic"] = topic
    await ctx.bot.send_message(
        update.effective_chat.id,
        f"Тема: <b>{topic}</b>\nПришлите ваш план.",
        parse_mode='HTML'
    )
    return

async def stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    # удаляем текущее сообщение с меню/планом
    try:
        await update.callback_query.message.delete()
    except:
        pass
    await ctx.bot.send_message(update.effective_chat.id, "Сеанс прерван. До свидания!")

# ——————————————————————————————————————————————————————————
# Получение текста плана
async def receive_plan(update: Update, ctx):
    topic = ctx.user_data.get("topic")
    ideal = BOT_DATA.get_plan_data(topic)
    fb = evaluate_plan(update.message.text, ideal, BOT_DATA, topic)
    await update.message.reply_html(fb, reply_markup=FEEDBACK_KB)

# ——————————————————————————————————————————————————————————
# Кнопки фидбека
async def cb_feedback(update: Update, ctx):
    data = update.callback_query.data
    if data == "back_main":
        await start(update, ctx)
    else:  # next_topic
        await start_train(update, ctx)

async def choose_task24_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Коллбек при нажатии кнопки «Задание 24» в главном меню."""
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "🔄 Перехожу к модулю «Задание 24 (План)».\n"
        "Введите /start_plan, чтобы начать работу."
    )
    # Здесь не нужен FSM-state, выходим из внешнего ConversationHandler
    return ConversationHandler.END
# ——————————————————————————————————————————————————————————
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start_list,    pattern="^start_list$"))
    app.add_handler(CallbackQueryHandler(start_train, pattern="^start_train$"))
    app.add_handler(CallbackQueryHandler(select_topic, pattern="^select_block:"))
    app.add_handler(CallbackQueryHandler(stop,          pattern="^stop$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_plan))
    app.add_handler(CallbackQueryHandler(cb_feedback, pattern="^(back_main|next_topic)$"))
    app.run_polling()

def register_task24_handlers(app):
    app.add_handler(CommandHandler("start_plan", start), group=1)
    # Кнопки меню
    app.add_handler(CallbackQueryHandler(start_list, pattern="^start_list$"))
    app.add_handler(CallbackQueryHandler(start_train, pattern="^start_train$"))
    app.add_handler(CallbackQueryHandler(select_topic, pattern="^select_block:"))
    app.add_handler(CallbackQueryHandler(stop, pattern="^stop$"))
    # Приём плана (после выбора темы)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_plan))
    # Кнопки фидбека
    app.add_handler(CallbackQueryHandler(cb_feedback, pattern="^(back_main|next_topic)$"))


if __name__ == "__main__":
    main()
