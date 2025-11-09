"""
Обработчики для личного кабинета пользователя.
"""

import logging
import aiosqlite
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from core.db import DATABASE_FILE
from payment.subscription_manager import SubscriptionManager
from core.user_segments import get_segment_classifier

from .keyboards import (
    get_main_cabinet_keyboard,
    get_subscription_keyboard,
    get_statistics_keyboard,
    get_settings_keyboard
)

logger = logging.getLogger(__name__)

# Состояния
VIEWING = 1

# Инициализация менеджеров
subscription_manager = SubscriptionManager()
classifier = get_segment_classifier()


async def show_personal_cabinet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает главное меню личного кабинета.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "друг"

    text = (
        f"👤 <b>Личный кабинет</b>\n\n"
        f"Привет, {first_name}! 👋\n\n"
        f"Здесь ты можешь управлять своей подпиской, "
        f"отслеживать прогресс и настраивать уведомления.\n\n"
        f"📚 Выбери нужный раздел:"
    )

    keyboard = get_main_cabinet_keyboard()

    await query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return VIEWING


async def show_subscription_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает информацию о подписке пользователя.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем информацию о подписке
    sub_info = await classifier.get_subscription_info(user_id)
    has_subscription = sub_info.get('has_subscription', False)

    # Формируем текст
    if has_subscription:
        plan_id = sub_info.get('plan_id', 'unknown')
        end_date = sub_info.get('end_date')
        days_left = sub_info.get('days_until_expiry', 0)
        is_trial = sub_info.get('is_trial', False)
        auto_renew = sub_info.get('auto_renew', False)

        # Определяем название плана
        if is_trial:
            plan_name = "🎁 Пробный период"
        else:
            plan_name = f"📦 {plan_id}"

        # Форматируем дату окончания
        if end_date:
            end_date_str = end_date.strftime("%d.%m.%Y")
        else:
            end_date_str = "неизвестно"

        # Эмодзи и статус для дней
        if days_left <= 3:
            days_emoji = "🔴"
            status_line = f"⚠️ <b>Истекает через {days_left} дн.</b>"
        elif days_left <= 7:
            days_emoji = "🟡"
            status_line = f"⚠️ <b>Истекает через {days_left} дн.</b>"
        else:
            days_emoji = "✅"
            status_line = f"✅ <b>Активна до {end_date_str}</b>"

        # Визуальный прогресс-бар (30 дней = 100%)
        progress_days = 30  # Базовый период
        progress = min(days_left / progress_days, 1.0)
        filled = int(progress * 10)
        bar = "█" * filled + "░" * (10 - filled)

        # Статус автопродления
        auto_renew_status = "✅ Включено" if auto_renew else "❌ Отключено"

        text = (
            f"💳 <b>Моя подписка</b>\n\n"
            f"{status_line}\n\n"
            f"<b>Текущий план:</b> {plan_name}\n"
            f"<b>Окончание:</b> {end_date_str} ({days_emoji} {days_left} дн.)\n"
            f"<b>Прогресс:</b> {bar}\n"
            f"<b>Автопродление:</b> {auto_renew_status}\n\n"
        )

        if days_left <= 7 and not auto_renew:
            text += "⚠️ <i>Подписка скоро истечёт! Продли или включи автопродление.</i>\n\n"
        elif days_left <= 7 and auto_renew:
            text += "✅ <i>Автопродление включено — подписка обновится автоматически.</i>\n\n"

    else:
        # Нет активной подписки
        had_subscription = sub_info.get('had_subscription', False)

        if had_subscription:
            days_since_cancel = sub_info.get('days_since_cancel', 0)
            text = (
                f"💳 <b>Моя подписка</b>\n\n"
                f"❌ <b>У тебя нет активной подписки</b>\n\n"
                f"Подписка закончилась {days_since_cancel} дн. назад.\n\n"
                f"💡 Оформи подписку, чтобы получить доступ ко всем материалам "
                f"и неограниченным AI-проверкам!"
            )
        else:
            text = (
                f"💳 <b>Моя подписка</b>\n\n"
                f"🆓 <b>У тебя бесплатный доступ</b>\n\n"
                f"Ты можешь использовать:\n"
                f"• Бесплатные материалы\n"
                f"• 3 AI-проверки в день\n\n"
                f"💡 Оформи подписку, чтобы получить полный доступ!"
            )

    # Определяем параметры для клавиатуры
    can_toggle_auto_renew = has_subscription and not is_trial
    auto_renew_enabled = sub_info.get('auto_renew', False) if has_subscription else False

    keyboard = get_subscription_keyboard(
        has_subscription=has_subscription,
        auto_renew_enabled=auto_renew_enabled,
        can_toggle_auto_renew=can_toggle_auto_renew
    )

    await query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return VIEWING


async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает статистику пользователя.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем статистику
    activity = await classifier.get_user_activity_stats(user_id)

    if not activity:
        text = (
            "📊 <b>Статистика</b>\n\n"
            "❌ Не удалось загрузить статистику.\n"
            "Попробуй позже."
        )
        keyboard = get_statistics_keyboard()
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        return VIEWING

    # Извлекаем данные
    answered_total = activity.get('answered_total', 0)
    answered_week = activity.get('answered_week', 0)
    ai_checks_total = activity.get('ai_checks_total', 0)
    ai_checks_today = activity.get('ai_checks_today', 0)
    days_since_reg = activity.get('days_since_registration', 0)
    days_inactive = activity.get('days_inactive', 0)
    created_at = activity.get('created_at')

    # Дата регистрации
    if created_at:
        reg_date_str = created_at.strftime("%d.%m.%Y")
    else:
        reg_date_str = "неизвестно"

    # Активность
    if days_inactive == 0:
        activity_status = "🟢 Активен сегодня"
    elif days_inactive == 1:
        activity_status = "🟡 Был вчера"
    elif days_inactive <= 7:
        activity_status = f"🟡 Неактивен {days_inactive} дн."
    else:
        activity_status = f"🔴 Неактивен {days_inactive} дн."

    # Получаем информацию о подписке для AI-лимита
    sub_info = await classifier.get_subscription_info(user_id)
    has_subscription = sub_info.get('has_subscription', False)

    if has_subscription:
        ai_limit_text = "♾️ Безлимит"
    else:
        ai_limit_text = f"{ai_checks_today}/3 использовано сегодня"

    text = (
        f"📊 <b>Твоя статистика</b>\n\n"
        f"<b>📅 Зарегистрирован:</b> {reg_date_str}\n"
        f"<b>📆 Дней с нами:</b> {days_since_reg}\n"
        f"<b>🎯 Статус:</b> {activity_status}\n\n"
        f"<b>📝 Решено вопросов:</b>\n"
        f"• Всего: {answered_total}\n"
        f"• За неделю: {answered_week}\n\n"
        f"<b>🤖 AI-проверки:</b>\n"
        f"• Всего использовано: {ai_checks_total}\n"
        f"• Сегодня: {ai_limit_text}\n\n"
        f"💪 Продолжай в том же духе!"
    )

    keyboard = get_statistics_keyboard()

    await query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return VIEWING


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает настройки пользователя.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем статус уведомлений
    notifications_enabled = await get_notification_status(user_id)

    # Формируем текст
    notif_status = "✅ Включены" if notifications_enabled else "❌ Отключены"

    text = (
        f"⚙️ <b>Настройки</b>\n\n"
        f"<b>🔔 Уведомления:</b> {notif_status}\n\n"
        f"Здесь ты можешь управлять своими настройками.\n\n"
        f"💡 <i>Мы отправляем не более 1 уведомления в день с полезными "
        f"напоминаниями и персональными предложениями.</i>"
    )

    keyboard = get_settings_keyboard(notifications_enabled)

    await query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return VIEWING


async def get_notification_status(user_id: int) -> bool:
    """
    Получает статус уведомлений пользователя.

    Args:
        user_id: ID пользователя

    Returns:
        True если уведомления включены, False иначе
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT enabled FROM notification_preferences
                WHERE user_id = ?
            """, (user_id,))
            row = await cursor.fetchone()

            if row:
                return bool(row[0])
            else:
                # По умолчанию уведомления включены
                return True

    except Exception as e:
        logger.error(f"Error getting notification status for user {user_id}: {e}")
        return True


async def handle_notification_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Переключает статус уведомлений.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем текущий статус
    current_status = await get_notification_status(user_id)
    new_status = not current_status

    # Обновляем в БД
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                INSERT OR REPLACE INTO notification_preferences (
                    user_id, enabled, disabled_at, disabled_reason
                ) VALUES (?, ?, ?, ?)
            """, (
                user_id,
                1 if new_status else 0,
                None if new_status else datetime.now(timezone.utc).isoformat(),
                None if new_status else 'user_request'
            ))
            await db.commit()

        logger.info(f"User {user_id} {'enabled' if new_status else 'disabled'} notifications")

        # Показываем обновленные настройки
        await show_settings(update, context)

    except Exception as e:
        logger.error(f"Error toggling notifications for user {user_id}: {e}")
        await query.answer("❌ Ошибка при изменении настроек", show_alert=True)

    return VIEWING


async def handle_auto_renewal_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Переключает автопродление подписки.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        # Получаем информацию о подписке
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Проверяем текущий статус автопродления
            cursor = await db.execute("""
                SELECT auto_renew FROM subscriptions
                WHERE user_id = ? AND is_active = 1
                ORDER BY end_date DESC
                LIMIT 1
            """, (user_id,))
            row = await cursor.fetchone()

            if not row:
                await query.answer("❌ Нет активной подписки", show_alert=True)
                return VIEWING

            current_auto_renew = bool(row[0])
            new_auto_renew = not current_auto_renew

            # Обновляем статус
            await db.execute("""
                UPDATE subscriptions
                SET auto_renew = ?
                WHERE user_id = ? AND is_active = 1
            """, (1 if new_auto_renew else 0, user_id))
            await db.commit()

        logger.info(f"User {user_id} {'enabled' if new_auto_renew else 'disabled'} auto-renewal")

        # Показываем обновленную информацию о подписке
        await show_subscription_info(update, context)

    except Exception as e:
        logger.error(f"Error toggling auto-renewal for user {user_id}: {e}")
        await query.answer("❌ Ошибка при изменении автопродления", show_alert=True)

    return VIEWING


async def handle_buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Перенаправляет пользователя к покупке/продлению подписки.
    Напрямую открывает магазин подписок.
    """
    try:
        from payment.handlers import show_modular_interface

        # Прямой переход к магазину подписок
        await show_modular_interface(update, context)

        # Завершаем текущий ConversationHandler для перехода к процессу оплаты
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error redirecting to subscription shop: {e}")
        query = update.callback_query
        if query:
            await query.answer("❌ Ошибка при переходе к оформлению подписки", show_alert=True)
        return VIEWING
