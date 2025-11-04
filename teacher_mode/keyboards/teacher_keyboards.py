"""
Клавиатуры для учителей.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


def get_teacher_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню учителя"""
    keyboard = [
        [InlineKeyboardButton("👥 Мои ученики", callback_data="teacher_students")],
        [InlineKeyboardButton("➕ Создать задание", callback_data="teacher_create_assignment")],
        [InlineKeyboardButton("📊 Статистика", callback_data="teacher_statistics")],
        [InlineKeyboardButton("🎁 Подарить подписку", callback_data="teacher_gift_subscription")],
        [InlineKeyboardButton("🔑 Промокоды", callback_data="teacher_promo_codes")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="teacher_profile")],
        [InlineKeyboardButton("◀️ Назад в главное меню", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_to_teacher_menu_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в меню учителя"""
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]]
    return InlineKeyboardMarkup(keyboard)
