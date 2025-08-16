# payment/auto_renewal_handlers.py - Новый файл с обработчиками автопродления

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from telegram.constants import ParseMode
from .subscription_manager import SubscriptionManager
from core.error_handler import safe_handler  # Исправленный импорт

logger = logging.getLogger(__name__)

@safe_handler()
async def cmd_auto_renewal_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для проверки статуса автопродления."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    try:
        # Получаем статус автопродления
        auto_renewal = await subscription_manager.get_auto_renewal_status(user_id)
        
        if not auto_renewal:
            text = """🔄 <b>Автопродление подписки</b>

У вас не настроено автопродление подписки.

С автопродлением ваша подписка будет автоматически продлеваться каждый месяц, и вы не потеряете доступ к материалам."""
            
            keyboard = [[
                InlineKeyboardButton("✅ Включить автопродление", 
                                   callback_data="enable_auto_renewal")
            ]]
        else:
            if auto_renewal['enabled']:
                text = f"""✅ <b>Автопродление включено</b>

📅 Следующее списание: {auto_renewal['next_renewal_date'].strftime('%d.%m.%Y')}
💳 Способ оплаты: {'Сохраненная карта' if auto_renewal['payment_method'] == 'card' else 'Рекуррентный платеж'}

Подписка будет автоматически продлена в указанную дату."""
                
                keyboard = [[
                    InlineKeyboardButton("❌ Отключить автопродление", 
                                       callback_data="disable_auto_renewal")
                ]]
            else:
                text = """❌ <b>Автопродление отключено</b>

Автопродление было отключено. Вы можете включить его снова в любой момент."""
                
                keyboard = [[
                    InlineKeyboardButton("✅ Включить автопродление", 
                                       callback_data="enable_auto_renewal")
                ]]
        
        keyboard.append([
            InlineKeyboardButton("📋 Мои подписки", callback_data="my_subscriptions")
        ])
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error checking auto-renewal status: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке статуса автопродления."
        )

@safe_handler()
async def handle_enable_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка включения автопродления."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    try:
        # Проверяем наличие активной подписки
        subscription = await subscription_manager.check_active_subscription(user_id)
        
        if not subscription:
            await query.edit_message_text(
                "❌ У вас нет активной подписки для настройки автопродления.\n\n"
                "Сначала оформите подписку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💳 Оформить подписку", 
                                       callback_data="subscribe_start")
                ]])
            )
            return
        
        # Проверяем наличие сохраненной карты или рекуррентного токена
        payment_info = await subscription_manager.get_last_payment_info(user_id)
        
        if not payment_info or not payment_info.get('recurrent_id'):
            text = """💳 <b>Настройка автопродления</b>

Для включения автопродления необходимо привязать карту.

При следующей оплате выберите опцию "Сохранить карту для автопродления"."""
            
            keyboard = [[
                InlineKeyboardButton("💳 Привязать карту", 
                                   callback_data="renew_subscription")
            ]]
        else:
            # Включаем автопродление
            success = await subscription_manager.enable_auto_renewal(
                user_id,
                payment_method='recurrent',
                recurrent_token=payment_info['recurrent_id']
            )
            
            if success:
                text = f"""✅ <b>Автопродление успешно включено!</b>

📅 Следующее списание: {subscription['expires_at'].strftime('%d.%m.%Y')}
💰 Сумма: {subscription.get('amount', 0)} ₽

Вы получите уведомление за 3 дня до списания."""
                
                keyboard = [[
                    InlineKeyboardButton("✅ Отлично!", callback_data="close_message")
                ]]
            else:
                text = "❌ Не удалось включить автопродление. Попробуйте позже."
                keyboard = []
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
        
    except Exception as e:
        logger.error(f"Error enabling auto-renewal: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

@safe_handler()
async def handle_disable_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка отключения автопродления."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    # Подтверждение отключения
    if query.data == "disable_auto_renewal":
        text = """⚠️ <b>Отключение автопродления</b>

Вы уверены, что хотите отключить автопродление?

После отключения ваша подписка не будет продлеваться автоматически, и вы можете потерять доступ к материалам после истечения текущего периода."""
        
        keyboard = [
            [
                InlineKeyboardButton("❌ Да, отключить", 
                                   callback_data="confirm_disable_auto_renewal"),
                InlineKeyboardButton("✅ Оставить", 
                                   callback_data="close_message")
            ]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Подтверждено - отключаем
    if query.data == "confirm_disable_auto_renewal":
        try:
            success = await subscription_manager.disable_auto_renewal(user_id)
            
            if success:
                text = """✅ <b>Автопродление отключено</b>

Автоматическое продление подписки отключено.

Ваша текущая подписка будет действовать до конца оплаченного периода.

Вы можете включить автопродление снова в любой момент."""
                
                keyboard = [[
                    InlineKeyboardButton("📋 Мои подписки", 
                                       callback_data="my_subscriptions")
                ]]
            else:
                text = "❌ Не удалось отключить автопродление. Попробуйте позже."
                keyboard = []
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
            
        except Exception as e:
            logger.error(f"Error disabling auto-renewal: {e}")
            await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

@safe_handler()
async def handle_renew_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка продления подписки."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    try:
        # Получаем информацию о последней подписке
        last_subscription = await subscription_manager.get_last_subscription_info(user_id)
        
        if last_subscription:
            # Предлагаем продлить с тем же планом
            text = f"""💳 <b>Продление подписки</b>

Продлить подписку "{last_subscription['plan_name']}"?

💰 Стоимость: {last_subscription['amount']} ₽/мес"""
            
            keyboard = [
                [InlineKeyboardButton(f"✅ Продлить за {last_subscription['amount']} ₽", 
                                     callback_data=f"pay_plan_{last_subscription['plan_id']}")],
                [InlineKeyboardButton("🔄 Выбрать другой план", 
                                     callback_data="subscribe_start")],
                [InlineKeyboardButton("❌ Отмена", 
                                     callback_data="close_message")]
            ]
        else:
            # Перенаправляем на выбор плана
            text = "Выберите план подписки:"
            keyboard = [[
                InlineKeyboardButton("💳 Выбрать план", 
                                   callback_data="subscribe_start")
            ]]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error handling subscription renewal: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

def register_auto_renewal_handlers(app):
    """Регистрирует обработчики автопродления."""
    
    # Команды
    app.add_handler(CommandHandler("auto_renewal", cmd_auto_renewal_status))
    
    # Callback обработчики
    app.add_handler(CallbackQueryHandler(
        handle_enable_auto_renewal, 
        pattern="^enable_auto_renewal$"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_disable_auto_renewal, 
        pattern="^(disable_auto_renewal|confirm_disable_auto_renewal)$"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_renew_subscription, 
        pattern="^renew_subscription$"
    ))
    
    logger.info("Auto-renewal handlers registered")