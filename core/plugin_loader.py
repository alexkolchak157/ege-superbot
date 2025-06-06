# core/plugin_loader.py
import importlib, pkgutil
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .plugin_base import BotPlugin

PLUGINS: List[BotPlugin] = []

def discover_plugins() -> None:
    """Ищем модули *.plugin.py в корне проекта."""
    for mod in pkgutil.iter_modules():
        # расширяйте условие по мере появления новых пакетов
        if mod.name in ("test_part", "task24", "task19"):
            plugin_module = importlib.import_module(f"{mod.name}.plugin")
            PLUGINS.append(plugin_module.plugin)
    PLUGINS.sort(key=lambda p: p.menu_priority)

def build_main_menu() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(p.title,
                                     callback_data=f"choose_{p.code}")]
               for p in PLUGINS]
    return InlineKeyboardMarkup(buttons)
