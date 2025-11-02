"""
Scheduler для автоматической отправки retention уведомлений.

Запускается ежедневно через Telegram Job Queue.
Классифицирует пользователей и отправляет персонализированные уведомления.
"""

import logging
import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest

from core.db import DATABASE_FILE
from core.user_segments import get_segment_classifier, UserSegment
from core.notification_templates import (
    get_template,
    NotificationTrigger,
    NotificationTemplate
)

logger = logging.getLogger(__name__)


class RetentionScheduler:
    """Планировщик retention уведомлений"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file
        self.classifier = get_segment_classifier()

    async def can_send_notification(
        self,
        user_id: int,
        trigger: NotificationTrigger
    ) -> Tuple[bool, str]:
        """
        Проверяет можно ли отправить уведомление пользователю.

        Returns:
            (can_send, reason)
        """
        async with aiosqlite.connect(self.database_file) as db:
            # Проверка 1: Пользователь отписался?
            cursor = await db.execute("""
                SELECT enabled FROM notification_preferences
                WHERE user_id = ?
            """, (user_id,))
            pref = await cursor.fetchone()

            if pref and not pref[0]:
                return False, "user_disabled"

            # Проверка 2: Лимит уведомлений в день
            cursor = await db.execute("""
                SELECT notification_count_today FROM notification_preferences
                WHERE user_id = ?
            """, (user_id,))
            count_row = await cursor.fetchone()

            if count_row and count_row[0] >= 1:  # Максимум 1 в день
                return False, "daily_limit_exceeded"

            # Проверка 3: Cooldown для этого триггера
            cursor = await db.execute("""
                SELECT cooldown_until FROM notification_cooldown
                WHERE user_id = ? AND trigger = ?
                AND cooldown_until > datetime('now')
            """, (user_id, trigger.value))
            cooldown = await cursor.fetchone()

            if cooldown:
                return False, "trigger_cooldown"

            # Проверка 4: Уже отправляли это уведомление?
            cursor = await db.execute("""
                SELECT id FROM notification_log
                WHERE user_id = ? AND trigger = ?
                AND sent_at > datetime('now', '-7 days')
            """, (user_id, trigger.value))
            recent = await cursor.fetchone()

            if recent:
                return False, "already_sent_recently"

            return True, "ok"

    async def log_notification(
        self,
        user_id: int,
        segment: UserSegment,
        trigger: NotificationTrigger,
        promo_code: Optional[str] = None
    ):
        """Логирует отправленное уведомление"""
        async with aiosqlite.connect(self.database_file) as db:
            await db.execute("""
                INSERT INTO notification_log (
                    user_id, segment, trigger, promo_code, sent_at
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                segment.value,
                trigger.value,
                promo_code,
                datetime.now(timezone.utc)
            ))

            # Устанавливаем cooldown (24 часа для этого триггера)
            await db.execute("""
                INSERT OR REPLACE INTO notification_cooldown (
                    user_id, trigger, cooldown_until
                ) VALUES (?, ?, ?)
            """, (
                user_id,
                trigger.value,
                (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            ))

            await db.commit()

    def extract_promo_code(self, text: str) -> Optional[str]:
        """Извлекает промокод из текста уведомления"""
        import re
        # Ищем паттерны типа "Промокод: TOP20" или "LASTDAY25"
        patterns = [
            r'Промокод:\s*(\w+)',
            r'промокод[:\s]+(\w+)',
            r'\b([A-Z]{3,}\d{2})\b'  # TOP20, SAVE25, etc.
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)

        return None

    async def send_notification(
        self,
        bot: Bot,
        user_id: int,
        segment: UserSegment,
        trigger: NotificationTrigger,
        variables: Dict[str, Any]
    ) -> bool:
        """
        Отправляет уведомление пользователю.

        Returns:
            True если успешно отправлено
        """
        # Проверяем можно ли отправить
        can_send, reason = await self.can_send_notification(user_id, trigger)
        if not can_send:
            logger.debug(f"Cannot send {trigger.value} to {user_id}: {reason}")
            return False

        # Получаем шаблон
        template = get_template(trigger)
        if not template:
            logger.error(f"Template not found for trigger: {trigger.value}")
            return False

        # Рендерим текст
        text = template.render(variables)

        # Создаём кнопки
        buttons = []
        for btn in template.buttons:
            if 'url' in btn:
                buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
            else:
                buttons.append([InlineKeyboardButton(btn['text'], callback_data=btn['callback_data'])])

        keyboard = InlineKeyboardMarkup(buttons) if buttons else None

        # Пытаемся отправить
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )

            # Извлекаем промокод из текста
            promo_code = self.extract_promo_code(text)

            # Логируем отправку
            await self.log_notification(user_id, segment, trigger, promo_code)

            logger.info(f"Sent {trigger.value} notification to user {user_id}")
            return True

        except Forbidden:
            logger.warning(f"User {user_id} blocked the bot")
            # Отключаем уведомления для этого пользователя
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO notification_preferences (
                        user_id, enabled, disabled_at, disabled_reason
                    ) VALUES (?, 0, ?, 'bot_blocked')
                """, (user_id, datetime.now(timezone.utc)))
                await db.commit()
            return False

        except BadRequest as e:
            logger.error(f"BadRequest sending to {user_id}: {e}")
            return False

        except Exception as e:
            logger.error(f"Error sending notification to {user_id}: {e}")
            return False

    async def process_bounced_users(self, bot: Bot) -> int:
        """Обрабатывает BOUNCED пользователей"""
        sent_count = 0

        # День 1: пользователи зарегистрировались вчера
        bounced_users = await self.classifier.get_users_by_segment(
            UserSegment.BOUNCED,
            limit=50
        )

        for user_id in bounced_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            if not activity:
                continue

            days_since_reg = activity['days_since_registration']

            # Определяем триггер
            if days_since_reg == 1:
                trigger = NotificationTrigger.BOUNCED_DAY1
            elif days_since_reg == 3:
                trigger = NotificationTrigger.BOUNCED_DAY3
            else:
                continue

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.BOUNCED,
                trigger=trigger,
                variables={
                    'first_name': activity['first_name'] or 'друг',
                    'answered_total': activity['answered_total']
                }
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_trial_users(self, bot: Bot) -> int:
        """Обрабатывает TRIAL пользователей"""
        sent_count = 0

        trial_users = await self.classifier.get_users_by_segment(
            UserSegment.TRIAL_USER,
            limit=50
        )

        for user_id in trial_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            subscription = await self.classifier.get_subscription_info(user_id)

            if not activity or not subscription.get('has_subscription'):
                continue

            days_until_expiry = subscription.get('days_until_expiry', 999)
            days_since_start = subscription.get('days_since_start', 0)

            # Определяем триггер
            if days_since_start == 3:
                trigger = NotificationTrigger.TRIAL_DAY3
            elif days_until_expiry == 2:
                trigger = NotificationTrigger.TRIAL_EXPIRING_2DAYS
            elif days_until_expiry == 1:
                trigger = NotificationTrigger.TRIAL_EXPIRING_1DAY
            elif days_until_expiry <= 0:
                trigger = NotificationTrigger.TRIAL_EXPIRED
            else:
                continue

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.TRIAL_USER,
                trigger=trigger,
                variables={
                    'first_name': activity['first_name'] or 'друг',
                    'answered_total': activity['answered_total'],
                    'ai_checks_total': activity['ai_checks_total'],
                    'days_until_expiry': max(0, days_until_expiry)
                }
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_churn_risk_users(self, bot: Bot) -> int:
        """Обрабатывает CHURN_RISK пользователей"""
        sent_count = 0

        churn_users = await self.classifier.get_users_by_segment(
            UserSegment.CHURN_RISK,
            limit=50
        )

        for user_id in churn_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            subscription = await self.classifier.get_subscription_info(user_id)

            if not activity or not subscription.get('has_subscription'):
                continue

            days_until_expiry = subscription.get('days_until_expiry', 999)

            # Определяем триггер
            if days_until_expiry == 7:
                trigger = NotificationTrigger.CHURN_RISK_7DAYS
            elif days_until_expiry == 3:
                trigger = NotificationTrigger.CHURN_RISK_3DAYS
            elif days_until_expiry == 1:
                trigger = NotificationTrigger.CHURN_RISK_1DAY
            else:
                continue

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.CHURN_RISK,
                trigger=trigger,
                variables={
                    'first_name': activity['first_name'] or 'друг',
                    'answered_total': activity['answered_total'],
                    'days_until_expiry': max(0, days_until_expiry)
                }
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_curious_users(self, bot: Bot) -> int:
        """Обрабатывает CURIOUS пользователей"""
        sent_count = 0

        curious_users = await self.classifier.get_users_by_segment(
            UserSegment.CURIOUS,
            limit=50
        )

        for user_id in curious_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            if not activity:
                continue

            days_inactive = activity['days_inactive']

            # Определяем триггер
            if days_inactive == 3:
                trigger = NotificationTrigger.CURIOUS_DAY3
            elif days_inactive == 7:
                trigger = NotificationTrigger.CURIOUS_DAY7
            else:
                continue

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.CURIOUS,
                trigger=trigger,
                variables={
                    'first_name': activity['first_name'] or 'друг',
                    'answered_total': activity['answered_total']
                }
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_active_free_users(self, bot: Bot) -> int:
        """Обрабатывает ACTIVE_FREE пользователей"""
        sent_count = 0

        active_free_users = await self.classifier.get_users_by_segment(
            UserSegment.ACTIVE_FREE,
            limit=50
        )

        for user_id in active_free_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            if not activity:
                continue

            days_since_reg = activity['days_since_registration']
            ai_checks_today = activity['ai_checks_today']

            # Определяем триггер
            if days_since_reg == 10:
                trigger = NotificationTrigger.ACTIVE_FREE_DAY10
            elif days_since_reg == 20:
                trigger = NotificationTrigger.ACTIVE_FREE_DAY20
            elif ai_checks_today >= 3:  # Использовал дневной лимит
                trigger = NotificationTrigger.ACTIVE_FREE_LIMIT_WARNING
            else:
                continue

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.ACTIVE_FREE,
                trigger=trigger,
                variables={
                    'first_name': activity['first_name'] or 'друг',
                    'answered_total': activity['answered_total'],
                    'ai_checks_total': activity['ai_checks_total']
                }
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_paying_inactive_users(self, bot: Bot) -> int:
        """Обрабатывает PAYING_INACTIVE пользователей"""
        sent_count = 0

        paying_inactive_users = await self.classifier.get_users_by_segment(
            UserSegment.PAYING_INACTIVE,
            limit=50
        )

        for user_id in paying_inactive_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            subscription = await self.classifier.get_subscription_info(user_id)

            if not activity or not subscription.get('has_subscription'):
                continue

            days_inactive = activity['days_inactive']

            # Определяем триггер
            if days_inactive == 3:
                trigger = NotificationTrigger.PAYING_INACTIVE_DAY3
            elif days_inactive == 7:
                trigger = NotificationTrigger.PAYING_INACTIVE_DAY7
            elif days_inactive == 14:
                trigger = NotificationTrigger.PAYING_INACTIVE_DAY14
            else:
                continue

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.PAYING_INACTIVE,
                trigger=trigger,
                variables={
                    'first_name': activity['first_name'] or 'друг',
                    'answered_total': activity['answered_total'],
                    'days_until_expiry': subscription.get('days_until_expiry', 0)
                }
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_cancelled_users(self, bot: Bot) -> int:
        """Обрабатывает CANCELLED пользователей"""
        sent_count = 0

        cancelled_users = await self.classifier.get_users_by_segment(
            UserSegment.CANCELLED,
            limit=50
        )

        for user_id in cancelled_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            subscription = await self.classifier.get_subscription_info(user_id)

            if not activity or not subscription.get('had_subscription'):
                continue

            days_since_cancel = subscription.get('days_since_cancel', 999)

            # Определяем триггер
            if days_since_cancel == 1:
                trigger = NotificationTrigger.CANCELLED_DAY1
            elif days_since_cancel == 3:
                trigger = NotificationTrigger.CANCELLED_DAY3
            elif days_since_cancel == 7:
                trigger = NotificationTrigger.CANCELLED_DAY7
            else:
                continue

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.CANCELLED,
                trigger=trigger,
                variables={
                    'first_name': activity['first_name'] or 'друг',
                    'answered_total': activity['answered_total']
                }
            )

            if success:
                sent_count += 1

        return sent_count

    async def send_daily_notifications(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Главная функция для ежедневной отправки уведомлений.
        Вызывается Job Queue.
        """
        bot = context.bot

        logger.info("=== Starting daily retention notifications ===")

        total_sent = 0

        # Обрабатываем каждый сегмент по приоритету
        try:
            # CHURN_RISK (критичный приоритет - первыми)
            churn_sent = await self.process_churn_risk_users(bot)
            total_sent += churn_sent
            logger.info(f"CHURN_RISK: sent {churn_sent} notifications")

            # TRIAL (высокий приоритет)
            trial_sent = await self.process_trial_users(bot)
            total_sent += trial_sent
            logger.info(f"TRIAL: sent {trial_sent} notifications")

            # BOUNCED (высокий приоритет)
            bounced_sent = await self.process_bounced_users(bot)
            total_sent += bounced_sent
            logger.info(f"BOUNCED: sent {bounced_sent} notifications")

            # CANCELLED (высокий приоритет - win-back)
            cancelled_sent = await self.process_cancelled_users(bot)
            total_sent += cancelled_sent
            logger.info(f"CANCELLED: sent {cancelled_sent} notifications")

            # CURIOUS (средний приоритет)
            curious_sent = await self.process_curious_users(bot)
            total_sent += curious_sent
            logger.info(f"CURIOUS: sent {curious_sent} notifications")

            # PAYING_INACTIVE (средний приоритет)
            paying_inactive_sent = await self.process_paying_inactive_users(bot)
            total_sent += paying_inactive_sent
            logger.info(f"PAYING_INACTIVE: sent {paying_inactive_sent} notifications")

            # ACTIVE_FREE (низкий приоритет - конверсионные)
            active_free_sent = await self.process_active_free_users(bot)
            total_sent += active_free_sent
            logger.info(f"ACTIVE_FREE: sent {active_free_sent} notifications")

        except Exception as e:
            logger.error(f"Error in daily retention notifications: {e}", exc_info=True)

        logger.info(f"=== Daily notifications complete: {total_sent} sent ===")


# Глобальный экземпляр
_scheduler_instance: Optional[RetentionScheduler] = None


def get_retention_scheduler() -> RetentionScheduler:
    """Возвращает глобальный экземпляр scheduler"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = RetentionScheduler()
    return _scheduler_instance
