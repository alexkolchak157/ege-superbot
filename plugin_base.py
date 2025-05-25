# core/plugin_base.py
from typing import Protocol
from telegram.ext import Application, CallbackQueryHandler

class BotPlugin(Protocol):
    code: str          # «test_part», «task24»…
    title: str         # подпись в главном меню
    menu_priority: int # порядок сортировки

    def register(self, app: Application) -> None: ...
    def entry_handler(self) -> CallbackQueryHandler: ...
