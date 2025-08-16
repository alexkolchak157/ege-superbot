# payment/scheduler.py - Новый файл для планировщика задач

import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

class SubscriptionScheduler:
    """Планировщик для автоматических задач подписок."""
    
    def __init__(self, bot: Bot, subscription_manager):
        self.bot = bot
        self.subscription_manager = subscription_manager
        self.scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
        self.setup_jobs()
    
    def setup_jobs(self):
        """Настраивает периодические задачи."""
        
        # Проверка истекающих подписок - каждый день в 10:00
        self.scheduler.add_job(
            self.check_expiring_subscriptions,
            CronTrigger(hour=10, minute=0),
            id='check_expiring_subscriptions',
            replace_existing=True,
            misfire_grace_time=3600
        )
        
        # Обработка автопродлений - каждый день в 02:00
        self.scheduler.add_job(
            self.process_auto_renewals,
            CronTrigger(hour=2, minute=0),
            id='process_auto_renewals',
            replace_existing=True,
            misfire_grace_time=3600
        )
        
        # Очистка старых уведомлений - раз в неделю
        self.scheduler.add_job(
            self.cleanup_old_notifications,
            CronTrigger(day_of_week='sun', hour=3, minute=0),
            id='cleanup_notifications',
            replace_existing=True
        )
        
        logger.info("Subscription scheduler jobs configured")
    
    def start(self):
        """Запускает планировщик."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Subscription scheduler started")
    
    def stop(self):
        """Останавливает планировщик."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Subscription scheduler stopped")
    
    async def check_expiring_subscriptions(self):
        """Проверяет и отправляет уведомления об истекающих подписках."""
        logger.info("Starting expiring subscriptions check...")
        
        notification_days = [7, 3, 1]  # За сколько дней предупреждать
        
        for days in notification_days:
            try:
                expiring = await self.subscription_manager.get_expiring_subscriptions(days)
                
                for subscription in expiring:
                    user_id = subscription['user_id']
                    expires_at = subscription['expires_at']
                    
                    # Определяем тип уведомления
                    notification_type = f'expiry_{days}days' if days > 1 else 'expiry_1day'
                    
                    # Проверяем, не отправляли ли уже
                    if await self.subscription_manager.has_notification_sent(
                        user_id, notification_type, expires_at
                    ):
                        continue
                    
                    # Отправляем уведомление
                    await self.send_expiry_notification(user_id, days, subscription)
                    
                    # Отмечаем как отправленное
                    await self.subscription_manager.mark_notification_sent(
                        user_id, notification_type, expires_at
                    )
                    
            except Exception as e:
                logger.error(f"Error checking expiring subscriptions for {days} days: {e}")
        
        # Проверяем истекшие подписки
        await self.check_expired_subscriptions()
        
        logger.info("Expiring subscriptions check completed")
    
    async def send_expiry_notification(self, user_id: int, days_remaining: int, subscription: dict):
        """Отправляет уведомление об истечении подписки."""
        try:
            # Получаем информацию об автопродлении
            auto_renewal = await self.subscription_manager.get_auto_renewal_status(user_id)
            
            if days_remaining == 7:
                emoji = "📅"
                urgency = "через неделю"
            elif days_remaining == 3:
                emoji = "⏰"
                urgency = "через 3 дня"
            elif days_remaining == 1:
                emoji = "⚠️"
                urgency = "завтра"
            else:
                emoji = "📆"
                urgency = f"через {days_remaining} дней"
            
            text = f"""{emoji} <b>Ваша подписка истекает {urgency}!</b>

📅 Дата окончания: {subscription['expires_at'].strftime('%d.%m.%Y')}"""
            
            if 'modules' in subscription:
                text += f"\n📦 Модули: {subscription['modules']}"
            
            if auto_renewal and auto_renewal.get('enabled'):
                text += "\n\n✅ У вас включено автопродление. Подписка будет продлена автоматически."
                
                keyboard = [[
                    InlineKeyboardButton("❌ Отключить автопродление", 
                                       callback_data="disable_auto_renewal")
                ]]
            else:
                text += "\n\n💡 Продлите подписку сейчас, чтобы не потерять доступ к материалам!"
                
                keyboard = [
                    [InlineKeyboardButton("💳 Продлить подписку", 
                                        callback_data="renew_subscription")],
                    [InlineKeyboardButton("🔄 Включить автопродление", 
                                        callback_data="enable_auto_renewal")]
                ]
            
            keyboard.append([InlineKeyboardButton("📋 Мои подписки", 
                                                 callback_data="my_subscriptions")])
            
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            logger.info(f"Sent {days_remaining}-day expiry notification to user {user_id}")
            
        except Exception as e:
            logger.error(f"Error sending expiry notification to user {user_id}: {e}")
    
    async def check_expired_subscriptions(self):
        """Проверяет и уведомляет об истекших подписках."""
        try:
            # Получаем подписки, истекшие вчера
            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            expired = await self.subscription_manager.get_expiring_subscriptions(-1)
            
            for subscription in expired:
                user_id = subscription['user_id']
                
                # Проверяем автопродление
                auto_renewal = await self.subscription_manager.get_auto_renewal_status(user_id)
                
                if auto_renewal and auto_renewal.get('enabled'):
                    # Пытаемся автоматически продлить
                    success = await self.subscription_manager.process_auto_renewal(user_id)
                    
                    if success:
                        await self.send_renewal_success_notification(user_id)
                    else:
                        await self.send_renewal_failure_notification(user_id)
                else:
                    # Отправляем уведомление об истечении
                    await self.send_expired_notification(user_id, subscription)
                    
        except Exception as e:
            logger.error(f"Error checking expired subscriptions: {e}")
    
    async def send_expired_notification(self, user_id: int, subscription: dict):
        """Отправляет уведомление об истекшей подписке."""
        try:
            text = """❌ <b>Ваша подписка истекла</b>

К сожалению, срок вашей подписки закончился. 
Вы больше не имеете доступа к платным материалам.

🔄 Восстановите доступ прямо сейчас!"""
            
            keyboard = [
                [InlineKeyboardButton("💳 Возобновить подписку", 
                                    callback_data="renew_subscription")],
                [InlineKeyboardButton("🎁 Специальное предложение", 
                                    callback_data="special_offer")]
            ]
            
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            logger.info(f"Sent expiration notification to user {user_id}")
            
        except Exception as e:
            logger.error(f"Error sending expiration notification: {e}")
    
    async def send_renewal_success_notification(self, user_id: int):
        """Уведомление об успешном автопродлении."""
        try:
            # Получаем информацию о новой подписке
            subscription = await self.subscription_manager.check_active_subscription(user_id)
            
            text = f"""✅ <b>Подписка автоматически продлена!</b>

Ваша подписка успешно продлена на следующий период.

📅 Действует до: {subscription['expires_at'].strftime('%d.%m.%Y')}

Спасибо, что остаетесь с нами! 🎉"""
            
            keyboard = [[
                InlineKeyboardButton("📋 Подробнее", callback_data="my_subscriptions")
            ]]
            
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error sending renewal success notification: {e}")
    
    async def send_renewal_failure_notification(self, user_id: int):
        """Уведомление о неудачном автопродлении."""
        try:
            text = """⚠️ <b>Не удалось автоматически продлить подписку</b>

К сожалению, при попытке автоматического продления произошла ошибка.

Возможные причины:
• Недостаточно средств на карте
• Истек срок действия карты
• Карта заблокирована

Пожалуйста, обновите платежные данные или продлите подписку вручную."""
            
            keyboard = [
                [InlineKeyboardButton("💳 Продлить вручную", 
                                    callback_data="renew_subscription")],
                [InlineKeyboardButton("🔧 Обновить карту", 
                                    callback_data="update_payment_method")],
                [InlineKeyboardButton("❌ Отключить автопродление", 
                                    callback_data="disable_auto_renewal")]
            ]
            
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error sending renewal failure notification: {e}")
    
    async def process_auto_renewals(self):
        """Обрабатывает все автопродления на сегодня."""
        logger.info("Starting auto-renewal processing...")
        
        try:
            # Получаем список пользователей для автопродления
            users_to_renew = await self.subscription_manager.get_users_for_auto_renewal()
            
            success_count = 0
            failure_count = 0
            
            for user_id in users_to_renew:
                try:
                    success = await self.subscription_manager.process_auto_renewal(user_id)
                    
                    if success:
                        success_count += 1
                        await self.send_renewal_success_notification(user_id)
                    else:
                        failure_count += 1
                        await self.send_renewal_failure_notification(user_id)
                        
                except Exception as e:
                    logger.error(f"Error processing auto-renewal for user {user_id}: {e}")
                    failure_count += 1
            
            # Отправляем отчет администраторам
            await self.send_renewal_report(success_count, failure_count)
            
        except Exception as e:
            logger.error(f"Error in auto-renewal processing: {e}")
        
        logger.info(f"Auto-renewal processing completed: {success_count} success, {failure_count} failures")
    
    async def send_renewal_report(self, success_count: int, failure_count: int):
        """Отправляет отчет об автопродлениях администраторам."""
        try:
            from core.config import ADMIN_IDS
            
            text = f"""📊 <b>Отчет об автопродлениях</b>

📅 Дата: {datetime.now().strftime('%d.%m.%Y')}

✅ Успешно продлено: {success_count}
❌ Ошибки продления: {failure_count}
📈 Всего обработано: {success_count + failure_count}

{'⚠️ Требуется внимание!' if failure_count > 0 else '✨ Все прошло успешно!'}"""
            
            for admin_id in ADMIN_IDS:
                try:
                    await self.bot.send_message(
                        chat_id=admin_id,
                        text=text,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error sending report to admin {admin_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error sending renewal report: {e}")
    
    async def cleanup_old_notifications(self):
        """Очищает старые записи уведомлений."""
        try:
            import aiosqlite
            
            # Удаляем уведомления старше 30 дней
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            
            async with aiosqlite.connect(self.subscription_manager.database_file) as conn:
                await conn.execute("""
                    DELETE FROM subscription_notifications 
                    WHERE sent_at < ?
                """, (cutoff_date,))
                
                await conn.commit()
                
            logger.info("Old notifications cleaned up")
            
        except Exception as e:
            logger.error(f"Error cleaning up notifications: {e}")