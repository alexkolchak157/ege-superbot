"""
Модуль для управления автопродлением подписок и согласиями пользователей.
Полноценная реализация с уведомлениями и многомесячными подписками.
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum

from aiogram import types, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

logger = logging.getLogger(__name__)

# Состояния для автопродления
class AutoRenewalStates(StatesGroup):
    SHOWING_TERMS = State()
    CONSENT_CHECKBOX = State()
    FINAL_CONFIRMATION = State()

# Экспортируем состояния для использования в handlers.py
SHOWING_TERMS = AutoRenewalStates.SHOWING_TERMS
CONSENT_CHECKBOX = AutoRenewalStates.CONSENT_CHECKBOX
FINAL_CONFIRMATION = AutoRenewalStates.FINAL_CONFIRMATION

class AutoRenewalConsent:
    """Класс для управления согласиями на автопродление."""
    
    def __init__(self, db_path: str = "/opt/ege-bot/subscriptions.db"):
        self.db_path = db_path
        
    async def show_auto_renewal_choice(self, update: types.Update, context: FSMContext):
        """Показать выбор типа оплаты с автопродлением или без."""
        
        plan_name = context.user_data.get('selected_plan', 'Стандарт')
        duration = context.user_data.get('duration_months', 1)
        price = context.user_data.get('price', 490)
        
        # Рассчитываем скидку для многомесячных подписок
        discount_text = ""
        if duration > 1:
            discount_percent = min(duration * 5, 20)  # Максимум 20% скидки
            discount_text = f"\n🎁 Скидка {discount_percent}% за оплату на {duration} мес."
        
        text = f"""💳 <b>Выберите способ оплаты</b>

📦 Тариф: <b>{plan_name}</b>
⏱ Период: <b>{duration} мес.</b>
💰 Стоимость: <b>{price} ₽</b>{discount_text}

Выберите удобный способ оплаты:"""

        keyboard = [
            [InlineKeyboardButton(
                "🔄 С автопродлением (удобнее)", 
                callback_data="choose_auto_renewal"
            )],
            [InlineKeyboardButton(
                "💳 Разовая оплата", 
                callback_data="choose_no_auto_renewal"
            )],
            [InlineKeyboardButton(
                "❓ Подробнее об автопродлении", 
                callback_data="show_auto_renewal_terms"
            )]
        ]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        return SHOWING_TERMS
    
    async def handle_choice_selection(self, update: types.CallbackQuery, context: FSMContext):
        """Обработка выбора типа оплаты."""
        query = update.callback_query
        await query.answer()
        
        if query.data == "choose_auto_renewal":
            # Переход к согласию на автопродление
            return await self.show_consent_form(update, context)
            
        elif query.data == "choose_no_auto_renewal":
            # Обычная оплата без автопродления
            context.user_data['enable_auto_renewal'] = False
            return await self.proceed_to_payment(update, context)
            
        elif query.data == "show_auto_renewal_terms":
            # Показать подробную информацию
            return await self.show_detailed_terms(update, context)
    
    async def show_consent_form(self, update: types.Update, context: FSMContext):
        """Показать форму согласия с чекбоксом."""
        
        plan_name = context.user_data.get('selected_plan', 'Стандарт')
        price = context.user_data.get('price', 490)
        duration = context.user_data.get('duration_months', 1)
        
        # Определяем период продления
        if duration == 1:
            renewal_period = "ежемесячно"
        elif duration == 3:
            renewal_period = "каждые 3 месяца"
        elif duration == 6:
            renewal_period = "каждые 6 месяцев"
        else:
            renewal_period = f"каждые {duration} месяцев"
        
        checkbox_state = context.user_data.get('consent_checkbox', False)
        checkbox_emoji = "☑️" if checkbox_state else "⬜"
        
        text = f"""📝 <b>Согласие на автоматическое продление</b>

Вы выбрали подписку с автопродлением.

📋 <b>Условия автопродления:</b>
• Списание будет происходить {renewal_period}
• Сумма списания: {price} ₽
• Уведомление за 3 дня до списания
• Отмена в любой момент через /my_subscriptions

{checkbox_emoji} <b>Нажмите для подтверждения согласия</b>

<i>Нажимая кнопку оплаты, вы соглашаетесь с условиями автоматического продления подписки и даете согласие на регулярное списание средств.</i>"""

        keyboard = [
            [InlineKeyboardButton(
                f"{checkbox_emoji} Подтвердить согласие",
                callback_data="toggle_consent_checkbox"
            )],
            [InlineKeyboardButton(
                "📜 Пользовательское соглашение",
                callback_data="show_user_agreement"
            )],
            [InlineKeyboardButton(
                "✅ Оплатить с автопродлением" if checkbox_state else "⚠️ Сначала подтвердите согласие",
                callback_data="confirm_with_auto_renewal" if checkbox_state else "need_consent_reminder"
            )],
            [InlineKeyboardButton(
                "◀️ Назад",
                callback_data="back_to_payment_choice"
            )]
        ]
        
        query = update.callback_query
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CONSENT_CHECKBOX
    
    async def toggle_consent(self, update: types.CallbackQuery, context: FSMContext):
        """Переключить состояние чекбокса согласия."""
        query = update.callback_query
        
        current_state = context.user_data.get('consent_checkbox', False)
        context.user_data['consent_checkbox'] = not current_state
        
        if not current_state:
            await query.answer("✅ Согласие подтверждено")
        else:
            await query.answer("⬜ Согласие отменено")
        
        # Обновляем форму
        return await self.show_consent_form(update, context)
    
    async def confirm_with_auto_renewal(self, update: types.CallbackQuery, context: FSMContext):
        """Подтвердить оплату с автопродлением."""
        query = update.callback_query
        
        if not context.user_data.get('consent_checkbox', False):
            await query.answer("⚠️ Сначала подтвердите согласие!", show_alert=True)
            return CONSENT_CHECKBOX
        
        # Сохраняем согласие в БД
        await self.save_consent_to_db(
            user_id=query.from_user.id,
            plan_id=context.user_data.get('selected_plan'),
            amount=context.user_data.get('price'),
            period_days=context.user_data.get('duration_months', 1) * 30
        )
        
        context.user_data['enable_auto_renewal'] = True
        await query.answer("✅ Переход к оплате с автопродлением")
        
        return await self.proceed_to_payment(update, context)
    
    async def proceed_to_payment(self, update: types.Update, context: FSMContext):
        """Переход к финальному подтверждению платежа."""
        query = update.callback_query
        
        plan_name = context.user_data.get('selected_plan', 'Стандарт')
        duration = context.user_data.get('duration_months', 1)
        price = context.user_data.get('price', 490)
        email = context.user_data.get('email', '')
        auto_renewal = context.user_data.get('enable_auto_renewal', False)
        
        renewal_text = "🔄 С автопродлением" if auto_renewal else "💳 Разовая оплата"
        
        text = f"""✅ <b>Подтверждение оплаты</b>

📋 <b>Детали заказа:</b>
• Тариф: <b>{plan_name}</b>
• Период: <b>{duration} мес.</b>
• Email: <b>{email}</b>
• Тип оплаты: <b>{renewal_text}</b>

💰 <b>К оплате: {price} ₽</b>

Нажмите "Оплатить" для перехода к платежной форме."""

        keyboard = [
            [InlineKeyboardButton(
                f"💳 Оплатить {price} ₽",
                callback_data="proceed_to_payment"
            )],
            [InlineKeyboardButton(
                "❌ Отменить",
                callback_data="cancel_payment"
            )]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return FINAL_CONFIRMATION
    
    async def save_consent_to_db(self, user_id: int, plan_id: str, amount: int, period_days: int):
        """Сохранить согласие пользователя в БД."""
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO auto_renewal_consents 
                (user_id, plan_id, amount, period_days, consent_text, consent_checkbox_state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                plan_id,
                amount,
                period_days,
                f"Согласие на автопродление подписки {plan_id} каждые {period_days} дней",
                1,
                datetime.now()
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Saved auto-renewal consent for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error saving consent: {e}")
    
    async def show_detailed_terms(self, update: types.CallbackQuery, context: FSMContext):
        """Показать подробные условия автопродления."""
        query = update.callback_query
        await query.answer()
        
        text = """📜 <b>Подробно об автопродлении</b>

<b>🔄 Как работает автопродление?</b>
После первой оплаты ваша карта сохраняется в защищенном виде. Каждый период (месяц/квартал) происходит автоматическое списание суммы подписки.

<b>💳 Безопасность платежей</b>
• Все платежи проходят через защищенный шлюз Тинькофф
• Данные карты хранятся в зашифрованном виде
• Соответствие стандарту PCI DSS

<b>🔔 Уведомления</b>
• За 3 дня до списания - напоминание
• После успешного списания - подтверждение
• При проблемах с оплатой - уведомление

<b>❌ Отмена автопродления</b>
• В любой момент через /my_subscriptions
• Мгновенное отключение
• Доступ сохраняется до конца оплаченного периода

<b>💰 Возвраты</b>
• В течение 14 дней - полный возврат
• После 14 дней - пропорциональный возврат

<b>📞 Поддержка</b>
По любым вопросам: /support"""
        
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="show_auto_renewal_choice")]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return SHOWING_TERMS
    
    async def handle_back_navigation(self, update: types.CallbackQuery, context: FSMContext):
        """Обработка навигации назад."""
        query = update.callback_query
        
        if query.data == "back_to_payment_choice":
            return await self.show_auto_renewal_choice(update, context)
        elif query.data == "show_auto_renewal_choice":
            return await self.show_auto_renewal_choice(update, context)


class SubscriptionNotificationManager:
    """Менеджер уведомлений о подписках."""
    
    def __init__(self, bot: Bot, db_path: str = "/opt/ege-bot/subscriptions.db"):
        self.bot = bot
        self.db_path = db_path
        self.is_running = False
        
    async def start(self):
        """Запустить проверку подписок."""
        if self.is_running:
            return
        
        self.is_running = True
        asyncio.create_task(self._notification_loop())
        logger.info("Subscription notification manager started")
    
    async def stop(self):
        """Остановить проверку подписок."""
        self.is_running = False
        logger.info("Subscription notification manager stopped")
    
    async def _notification_loop(self):
        """Основной цикл проверки подписок."""
        while self.is_running:
            try:
                await self.check_expiring_subscriptions()
                await self.process_auto_renewals()
                
                # Проверяем каждые 6 часов
                await asyncio.sleep(21600)
                
            except Exception as e:
                logger.error(f"Error in notification loop: {e}")
                await asyncio.sleep(300)  # При ошибке ждем 5 минут
    
    async def check_expiring_subscriptions(self):
        """Проверить истекающие подписки и отправить уведомления."""
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Находим подписки, истекающие через 3 дня
            three_days_later = datetime.now() + timedelta(days=3)
            
            cursor.execute("""
                SELECT DISTINCT user_id, plan_id, end_date, auto_renewal_enabled
                FROM expiring_subscriptions
                WHERE end_date BETWEEN ? AND ?
                AND last_notification_date IS NULL OR last_notification_date < ?
            """, (
                datetime.now(),
                three_days_later,
                datetime.now() - timedelta(days=1)
            ))
            
            expiring_subs = cursor.fetchall()
            
            for user_id, plan_id, end_date, auto_renewal in expiring_subs:
                await self.send_expiry_notification(
                    user_id, plan_id, end_date, bool(auto_renewal)
                )
                
                # Обновляем дату последнего уведомления
                cursor.execute("""
                    UPDATE expiring_subscriptions
                    SET last_notification_date = ?
                    WHERE user_id = ? AND plan_id = ?
                """, (datetime.now(), user_id, plan_id))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error checking expiring subscriptions: {e}")
    
    async def send_expiry_notification(self, user_id: int, plan_id: str, end_date: datetime, auto_renewal: bool):
        """Отправить уведомление об истечении подписки."""
        
        days_left = (end_date - datetime.now()).days
        
        if auto_renewal:
            text = f"""⏰ <b>Напоминание об автопродлении</b>

Ваша подписка "{plan_id}" будет автоматически продлена через {days_left} дней.

📅 Дата продления: {end_date.strftime('%d.%m.%Y')}
💳 Сумма списания: согласно тарифу

Если вы хотите отменить автопродление, используйте команду /my_subscriptions"""
        else:
            text = f"""⚠️ <b>Подписка скоро закончится</b>

Ваша подписка "{plan_id}" истекает через {days_left} дней.

📅 Дата окончания: {end_date.strftime('%d.%m.%Y')}

Чтобы продлить подписку, используйте команду /subscribe"""
        
        keyboard = [
            [InlineKeyboardButton(
                "🔄 Управление подпиской", 
                callback_data="manage_subscription"
            )]
        ]
        
        try:
            await self.bot.send_message(
                user_id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"Sent expiry notification to user {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to send notification to user {user_id}: {e}")
    
    async def process_auto_renewals(self):
        """Обработать автоматические продления подписок."""
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Находим подписки для автопродления
            cursor.execute("""
                SELECT user_id, plan_id, amount, recurrent_token
                FROM auto_renewal_settings
                WHERE enabled = 1 
                AND next_renewal_date <= ?
                AND failures_count < 3
            """, (datetime.now(),))
            
            renewals = cursor.fetchall()
            
            for user_id, plan_id, amount, token in renewals:
                success = await self.process_single_renewal(
                    user_id, plan_id, amount, token
                )
                
                if success:
                    # Обновляем дату следующего продления
                    next_date = datetime.now() + timedelta(days=30)
                    cursor.execute("""
                        UPDATE auto_renewal_settings
                        SET next_renewal_date = ?, failures_count = 0
                        WHERE user_id = ?
                    """, (next_date, user_id))
                    
                    # Записываем в историю
                    cursor.execute("""
                        INSERT INTO auto_renewal_history
                        (user_id, plan_id, status, amount, created_at)
                        VALUES (?, ?, 'success', ?, ?)
                    """, (user_id, plan_id, amount, datetime.now()))
                    
                else:
                    # Увеличиваем счетчик неудач
                    cursor.execute("""
                        UPDATE auto_renewal_settings
                        SET failures_count = failures_count + 1
                        WHERE user_id = ?
                    """, (user_id,))
                    
                    # Записываем неудачу в историю
                    cursor.execute("""
                        INSERT INTO auto_renewal_history
                        (user_id, plan_id, status, amount, error_message, created_at)
                        VALUES (?, ?, 'failed', ?, 'Payment failed', ?)
                    """, (user_id, plan_id, amount, datetime.now()))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error processing auto renewals: {e}")
    
    async def process_single_renewal(self, user_id: int, plan_id: str, amount: int, token: str) -> bool:
        """Обработать одно автопродление."""
        
        # Здесь должна быть интеграция с платежной системой
        # Пример для Тинькофф:
        try:
            from payment.tinkoff import TinkoffPayment
            
            tinkoff = TinkoffPayment()
            result = await tinkoff.charge_recurrent(
                rebill_id=token,
                amount=amount * 100,  # В копейках
                order_id=f"AUTO_{user_id}_{datetime.now().timestamp()}"
            )
            
            if result.get('Success'):
                # Отправляем уведомление об успешном продлении
                await self.bot.send_message(
                    user_id,
                    f"✅ Подписка '{plan_id}' успешно продлена!\n"
                    f"Списано: {amount} ₽\n"
                    f"Следующее продление: {(datetime.now() + timedelta(days=30)).strftime('%d.%m.%Y')}"
                )
                return True
            else:
                # Отправляем уведомление о проблеме
                await self.bot.send_message(
                    user_id,
                    f"❌ Не удалось продлить подписку '{plan_id}'.\n"
                    f"Проверьте баланс карты или обновите платежные данные.\n"
                    f"Используйте /my_subscriptions для управления подпиской."
                )
                return False
                
        except Exception as e:
            logger.error(f"Error charging recurrent payment for user {user_id}: {e}")
            return False


class MultiMonthSubscriptionManager:
    """Менеджер многомесячных подписок."""
    
    @staticmethod
    def calculate_discount(months: int) -> float:
        """Рассчитать скидку для многомесячной подписки."""
        discounts = {
            1: 0,      # Без скидки
            3: 0.10,   # 10% скидка
            6: 0.15,   # 15% скидка
            12: 0.20   # 20% скидка
        }
        return discounts.get(months, 0)
    
    @staticmethod
    def calculate_price(base_price: int, months: int) -> int:
        """Рассчитать итоговую цену с учетом скидки."""
        discount = MultiMonthSubscriptionManager.calculate_discount(months)
        total = base_price * months
        discounted = total * (1 - discount)
        return int(discounted)
    
    @staticmethod
    def get_duration_options(base_price: int) -> List[Dict[str, Any]]:
        """Получить варианты длительности подписки."""
        options = []
        
        for months in [1, 3, 6, 12]:
            price = MultiMonthSubscriptionManager.calculate_price(base_price, months)
            discount = MultiMonthSubscriptionManager.calculate_discount(months)
            
            option = {
                'months': months,
                'price': price,
                'discount_percent': int(discount * 100),
                'monthly_price': price // months,
                'savings': base_price * months - price
            }
            
            if months == 1:
                option['label'] = f"1 месяц - {price} ₽"
            elif months == 3:
                option['label'] = f"3 месяца - {price} ₽ (скидка {option['discount_percent']}%)"
            elif months == 6:
                option['label'] = f"6 месяцев - {price} ₽ (скидка {option['discount_percent']}%)"
            elif months == 12:
                option['label'] = f"1 год - {price} ₽ (скидка {option['discount_percent']}%)"
            
            options.append(option)
        
        return options


# Функция для использования в handlers.py
async def show_auto_renewal_choice(update: types.Update, context: FSMContext):
    """Обертка для вызова из handlers.py."""
    consent_handler = AutoRenewalConsent()
    return await consent_handler.show_auto_renewal_choice(update, context)


# Экспортируем необходимые классы и функции
__all__ = [
    'AutoRenewalConsent',
    'SubscriptionNotificationManager',
    'MultiMonthSubscriptionManager',
    'AutoRenewalStates',
    'SHOWING_TERMS',
    'CONSENT_CHECKBOX', 
    'FINAL_CONFIRMATION',
    'show_auto_renewal_choice'
]