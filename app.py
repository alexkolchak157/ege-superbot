from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
)
from core.plugin_loader import discover_plugins, build_main_menu, PLUGINS
from test_part.config import BOT_TOKEN


# ── 1. /start выводит меню ──────────────────────────────────────────────
async def start(update, ctx):
    await update.message.reply_text(
        "👋 Что хотите потренировать?",
        reply_markup=build_main_menu(),
    )


# ── 2. главный bootstrap ────────────────────────────────────────────────
def main():
    discover_plugins()

    app = (
    Application.builder()
    .token(BOT_TOKEN)
    .post_init(lambda _: app.bot.delete_webhook(drop_pending_updates=True))
    .build()
)

    # /start
    app.add_handler(CommandHandler("start", start))

    # entry-обработчики каждого плагина
    for p in PLUGINS:
        app.add_handler(p.entry_handler())
        p.register(app)             # все «внутренние» хендлеры плагина

    print("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()