"""
Шаблоны уведомлений для retention-кампаний.

Содержит персонализированные сообщения для каждого сегмента пользователей.
Все сообщения включают динамические переменные и countdown до ЕГЭ.
"""

import logging
from datetime import datetime, date
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)

# Дата ЕГЭ по обществознанию
EGE_DATE = date(2026, 6, 11)


def days_until_ege() -> int:
    """Возвращает количество дней до ЕГЭ"""
    today = date.today()
    delta = (EGE_DATE - today).days
    return max(0, delta)  # Не может быть отрицательным


class NotificationTrigger(Enum):
    """Триггеры для отправки уведомлений"""
    # Bounced сегмент
    BOUNCED_DAY1 = "bounced_day1"
    BOUNCED_DAY3 = "bounced_day3"

    # Curious сегмент
    CURIOUS_DAY3 = "curious_day3"
    CURIOUS_DAY7 = "curious_day7"

    # Active Free сегмент
    ACTIVE_FREE_DAY10 = "active_free_day10"
    ACTIVE_FREE_DAY20 = "active_free_day20"
    ACTIVE_FREE_LIMIT_WARNING = "active_free_limit_warning"

    # Trial Users сегмент
    TRIAL_DAY3 = "trial_day3"
    TRIAL_EXPIRING_2DAYS = "trial_expiring_2days"
    TRIAL_EXPIRING_1DAY = "trial_expiring_1day"
    TRIAL_EXPIRED = "trial_expired"

    # Paying Inactive сегмент
    PAYING_INACTIVE_DAY3 = "paying_inactive_day3"
    PAYING_INACTIVE_DAY7 = "paying_inactive_day7"
    PAYING_INACTIVE_DAY14 = "paying_inactive_day14"

    # Churn Risk сегмент
    CHURN_RISK_7DAYS = "churn_risk_7days"
    CHURN_RISK_3DAYS = "churn_risk_3days"
    CHURN_RISK_1DAY = "churn_risk_1day"

    # Cancelled сегмент
    CANCELLED_DAY1 = "cancelled_day1"
    CANCELLED_DAY3 = "cancelled_day3"
    CANCELLED_DAY7 = "cancelled_day7"


class NotificationTemplate:
    """Шаблон уведомления"""

    def __init__(self, text: str, buttons: Optional[List[Dict[str, str]]] = None):
        """
        Args:
            text: Текст сообщения (поддерживает переменные {var})
            buttons: Список кнопок [{"text": "...", "callback_data": "..."}]
        """
        self.text = text
        self.buttons = buttons or []

    def render(self, variables: Dict[str, Any]) -> str:
        """
        Рендерит шаблон с подстановкой переменных.

        Args:
            variables: Словарь переменных для подстановки

        Returns:
            Отрендеренный текст
        """
        # Добавляем автоматически days_to_ege
        variables['days_to_ege'] = days_until_ege()

        # Добавляем склонения дней
        days = variables.get('days_to_ege', 0)
        if days % 10 == 1 and days % 100 != 11:
            variables['days_word'] = 'день'
        elif days % 10 in [2, 3, 4] and days % 100 not in [12, 13, 14]:
            variables['days_word'] = 'дня'
        else:
            variables['days_word'] = 'дней'

        try:
            return self.text.format(**variables)
        except KeyError as e:
            logger.error(f"Missing variable in template: {e}")
            return self.text


# ==================== BOUNCED СЕГМЕНТ ====================

BOUNCED_TEMPLATES = {
    NotificationTrigger.BOUNCED_DAY1: NotificationTemplate(
        text="""📚 Привет, {first_name}!

Заметили, что ты ещё не начал подготовку.
Вот как это работает:

1️⃣ Нажми "📝 Тестовая часть"
2️⃣ Выбери любую тему
3️⃣ Реши 3-5 вопросов

Это займёт всего 5 минут, а ты поймёшь как это круто! 🚀

⏰ До ЕГЭ: {days_to_ege} {days_word}
Каждый день на счету!""",
        buttons=[
            {"text": "🚀 Начать прямо сейчас", "callback_data": "to_main_menu"},
            {"text": "🔕 Не беспокоить", "callback_data": "notifications_disable"}
        ]
    ),

    NotificationTrigger.BOUNCED_DAY3: NotificationTemplate(
        text="""💡 {first_name}, мы улучшили бота!

Теперь:
✨ Быстрее загружаются вопросы
✨ Понятнее объяснения ошибок
✨ Удобнее интерфейс

Идеальное время попробовать!

🎁 У тебя есть 3 бесплатных AI-проверки сегодня
Проверь любое задание второй части бесплатно!

⏰ До ЕГЭ осталось {days_to_ege} {days_word}""",
        buttons=[
            {"text": "💎 Попробовать AI-проверку", "callback_data": "choose_task24"},
            {"text": "📝 Начать с тестовой части", "callback_data": "choose_test_part"}
        ]
    )
}

# ==================== CURIOUS СЕГМЕНТ ====================

CURIOUS_TEMPLATES = {
    NotificationTrigger.CURIOUS_DAY3: NotificationTemplate(
        text="""💪 {first_name}, ты уже решил {answered_total} вопросов!

Но вот что интересно:
Ученики, которые решают хотя бы 10 вопросов,
в 3 раза чаще возвращаются и сдают ЕГЭ на 80+

Тебе осталось всего {questions_to_milestone} вопросов до первого достижения! 🎯

У тебя есть {checks_remaining} бесплатных AI-проверок сегодня.
Не упусти!

⏰ До ЕГЭ: {days_to_ege} {days_word}""",
        buttons=[
            {"text": "💯 Продолжить подготовку", "callback_data": "to_main_menu"},
            {"text": "🔕 Не сейчас", "callback_data": "notifications_snooze"}
        ]
    ),

    NotificationTrigger.CURIOUS_DAY7: NotificationTemplate(
        text="""📈 {first_name}, пока ты отсутствовал:

• Другие ученики решили в среднем 50+ вопросов
• 127 человек оформили подписку
• 89% из них улучшили результаты на 15+ баллов

Не отставай! 🚀

Твой прогресс: {answered_total} вопросов
До ЕГЭ: {days_to_ege} {days_word}

Продолжи подготовку и обгони остальных!""",
        buttons=[
            {"text": "🔥 Догнать и перегнать", "callback_data": "to_main_menu"},
            {"text": "💎 Узнать про подписку", "callback_data": "subscribe_start"}
        ]
    )
}

# ==================== ACTIVE FREE СЕГМЕНТ ====================

ACTIVE_FREE_TEMPLATES = {
    NotificationTrigger.ACTIVE_FREE_DAY10: NotificationTemplate(
        text="""🌟 {first_name}, у тебя отличный прогресс!

За последнюю неделю:
✅ {answered_week} правильных ответов
📈 Стрик: {current_streak} дней подряд
💯 Средний балл: растёт!

Знаешь что? Ученики с подпиской готовятся в 2 раза быстрее.
Вот почему:

• Безлимитные AI-проверки (сейчас у тебя только 3/день)
• Задания 19-25 (самые сложные, но дают 18 баллов!)
• Детальная аналитика слабых мест

🎁 Попробуй 7 дней за 1₽""",
        buttons=[
            {"text": "🎁 Попробовать за 1₽", "callback_data": "subscribe_start"},
            {"text": "💎 Узнать подробнее", "callback_data": "subscribe_start"}
        ]
    ),

    NotificationTrigger.ACTIVE_FREE_DAY20: NotificationTemplate(
        text="""🔥 Вау, {first_name}! Ты в топ-10% самых активных учеников!

Твои достижения:
🏆 Решено заданий: {answered_total}
📊 Дней подряд: {current_streak}
⭐ Ты молодец!

Но есть нюанс...
Вторая часть ЕГЭ даёт 60% баллов, а у тебя доступно только 3 проверки в день.

🎯 Ученики с Premium сдают на 90+:
• Безлимитные проверки AI
• Эталонные ответы по всем темам
• Личная статистика и рекомендации

До ЕГЭ {days_to_ege} {days_word}. Время действовать!

🎁 Специально для топовых: скидка 20%
Промокод: TOP20""",
        buttons=[
            {"text": "💎 Активировать скидку", "callback_data": "subscribe_start"},
            {"text": "📊 Посмотреть статистику", "callback_data": "to_main_menu"}
        ]
    ),

    NotificationTrigger.ACTIVE_FREE_LIMIT_WARNING: NotificationTemplate(
        text="""⚠️ {first_name}, осталась 1 бесплатная проверка!

Ты активно готовишься - это круто! 🔥
Но через 1 проверку лимит закончится до завтра.

💡 Не останавливайся на самом интересном!

С подпиской:
• Безлимитные проверки AI
• Проверка за секунды
• Детальный разбор каждой ошибки

🎁 Попробуй 7 дней за 1₽
До ЕГЭ {days_to_ege} {days_word} - не теряй темп!""",
        buttons=[
            {"text": "🚀 Попробовать за 1₽", "callback_data": "subscribe_start"},
            {"text": "⏰ Подожду до завтра", "callback_data": "notifications_snooze"}
        ]
    )
}

# ==================== TRIAL USERS СЕГМЕНТ ====================

TRIAL_TEMPLATES = {
    NotificationTrigger.TRIAL_DAY3: NotificationTemplate(
        text="""👋 {first_name}, как тебе trial?

Ты уже попробовал все функции?

✅ AI-проверку заданий 19-25
✅ Эталонные ответы
✅ Детальную аналитику

Если ещё нет - скорее тестируй!
До конца триала: {days_until_expiry} {days_word}

💡 Вопросы? Напиши @obshestvonapalcahsupport""",
        buttons=[
            {"text": "🎯 Проверить задание", "callback_data": "choose_task24"},
            {"text": "📊 Моя статистика", "callback_data": "to_main_menu"}
        ]
    ),

    NotificationTrigger.TRIAL_EXPIRING_2DAYS: NotificationTemplate(
        text="""⏰ {first_name}, через 2 дня твой trial закончится

За эти дни ты:
✅ Решил {answered_total} заданий второй части
✅ Получил {ai_checks_total} детальных проверок от AI
✅ Улучшил результаты!

🎯 Ученики с подпиской сдают на 15+ баллов выше!

Продли сейчас со скидкой 20% на первый месяц:
Вместо 249₽ → всего 199₽

Промокод: TRIAL20

⏰ До ЕГЭ: {days_to_ege} {days_word}""",
        buttons=[
            {"text": "💎 Продлить со скидкой", "callback_data": "subscribe_start"},
            {"text": "⏰ Напомнить завтра", "callback_data": "notifications_snooze"}
        ]
    ),

    NotificationTrigger.TRIAL_EXPIRING_1DAY: NotificationTemplate(
        text="""🚨 {first_name}, ЗАВТРА trial заканчивается!

Через 24 часа ты потеряешь:
❌ Безлимитные AI-проверки
❌ Задания 19-25
❌ Детальную аналитику
❌ Эталонные ответы

Твой прогресс:
📈 {answered_total} заданий решено
🎯 Средний балл растёт

Не останавливайся! Продли подписку со скидкой 25%:

🎁 LASTDAY25 — промокод на 25% скидку
(действует только сегодня)

До ЕГЭ {days_to_ege} {days_word}. Каждый день важен!""",
        buttons=[
            {"text": "🔥 Активировать LASTDAY25", "callback_data": "subscribe_start"},
            {"text": "❌ Откажусь от подписки", "callback_data": "trial_cancel_confirm"}
        ]
    ),

    NotificationTrigger.TRIAL_EXPIRED: NotificationTemplate(
        text="""⏰ {first_name}, твой trial истёк

Но вот факты:
• Ты решил {answered_total} заданий
• Ты видел свой прогресс
• Ты знаешь, что это работает

87% учеников, которые продлили trial,
говорят: "Лучшее вложение в подготовку"

🎁 ПОСЛЕДНИЙ ШАНС:
Продли в течение 24 часов и получи:
• Скидку 30% (промокод: COMEBACK30)
• +3 дня в подарок
• Бонусные материалы по сложным темам

До ЕГЭ {days_to_ege} {days_word}. Не упусти время!""",
        buttons=[
            {"text": "💎 Активировать COMEBACK30", "callback_data": "subscribe_start"},
            {"text": "🆓 Остаться на бесплатном", "callback_data": "to_main_menu"}
        ]
    )
}

# ==================== PAYING INACTIVE СЕГМЕНТ ====================

PAYING_INACTIVE_TEMPLATES = {
    NotificationTrigger.PAYING_INACTIVE_DAY3: NotificationTemplate(
        text="""💭 Скучаем по тебе, {first_name}!

Не заходил уже 3 дня. Всё в порядке?

Пока ты отсутствовал:
• Другие ученики прошли в среднем 12 новых тем
• До ЕГЭ осталось {days_to_ege} {days_word}

У тебя есть Premium-доступ до {subscription_end}.
Давай не будем терять его зря? 💪

Продолжи с любого задания:""",
        buttons=[
            {"text": "🎯 Задание 24 (План)", "callback_data": "choose_task24"},
            {"text": "📝 Тестовая часть", "callback_data": "choose_test_part"},
            {"text": "😔 Я передумал готовиться", "callback_data": "feedback_why_inactive"}
        ]
    ),

    NotificationTrigger.PAYING_INACTIVE_DAY7: NotificationTemplate(
        text="""😢 {first_name}, мы что-то делаем не так?

Ты не заходишь уже неделю, хотя подписка активна.

Может нам улучшить:
• Интерфейс бота?
• Объяснения ошибок?
• Сложность заданий?

💬 Напиши, что не нравится: @obshestvonapalcahsupport
Мы обязательно исправим!

Или может просто напомнить о подготовке?
До ЕГЭ {days_to_ege} {days_word} - время не ждёт!""",
        buttons=[
            {"text": "💪 Продолжить подготовку", "callback_data": "to_main_menu"},
            {"text": "💬 Написать в поддержку", "url": "https://t.me/obshestvonapalcahsupport"},
            {"text": "🔕 Отменить подписку", "callback_data": "cancel_subscription"}
        ]
    ),

    NotificationTrigger.PAYING_INACTIVE_DAY14: NotificationTemplate(
        text="""⚠️ {first_name}, подписка скоро закончится

Ты не заходил 2 недели.
Подписка активна до {subscription_end} ({days_until_expiry} {days_word}).

За твои деньги уходят впустую 💸

Может отменить автопродление?
Или всё-таки продолжим подготовку?

До ЕГЭ {days_to_ege} {days_word}.
Если не сейчас, то когда?""",
        buttons=[
            {"text": "🚀 Продолжить подготовку", "callback_data": "to_main_menu"},
            {"text": "⏸ Отключить автопродление", "callback_data": "disable_auto_renew"},
            {"text": "❌ Отменить подписку", "callback_data": "cancel_subscription"}
        ]
    )
}

# ==================== CHURN RISK СЕГМЕНТ ====================

CHURN_RISK_TEMPLATES = {
    NotificationTrigger.CHURN_RISK_7DAYS: NotificationTemplate(
        text="""⚠️ {first_name}, через неделю подписка закончится

Заметили, что ты стал заниматься реже.
Всё в порядке?

Твой прогресс:
📊 Решено: {answered_total} заданий
📈 Улучшение: видимый прогресс!
🎯 Осталось до цели: совсем чуть-чуть

Не останавливайся на полпути!

🎁 Продли сейчас и получи скидку 15%:
Промокод: STAY15

До ЕГЭ {days_to_ege} {days_word}""",
        buttons=[
            {"text": "💎 Продлить со скидкой", "callback_data": "subscribe_start"},
            {"text": "🔄 Настроить автопродление", "callback_data": "enable_auto_renew"}
        ]
    ),

    NotificationTrigger.CHURN_RISK_3DAYS: NotificationTemplate(
        text="""🚨 {first_name}, через 3 дня ты потеряешь весь прогресс!

Посмотри что ты достиг с нами:
📊 Решено {answered_total} заданий
📈 Прогресс: виден рост!
🎯 Твой средний балл вырос!

Не потеряй результат!

Продли подписку со скидкой 25%:
🎁 Промокод: SAVE25

Или настрой автопродление - удобно и выгодно!

До ЕГЭ {days_to_ege} {days_word}. Не сдавайся сейчас!""",
        buttons=[
            {"text": "💎 Продлить SAVE25", "callback_data": "subscribe_start"},
            {"text": "🔄 Включить автопродление", "callback_data": "enable_auto_renew"},
            {"text": "📊 Посмотреть прогресс", "callback_data": "to_main_menu"}
        ]
    ),

    NotificationTrigger.CHURN_RISK_1DAY: NotificationTemplate(
        text="""⚠️ КРИТИЧНО: {first_name}, ЗАВТРА подписка закончится!

Через 24 часа ты потеряешь:
❌ Безлимитные AI-проверки
❌ Все задания второй части
❌ Детальную аналитику
❌ Свой прогресс и статистику

Ты правда хочешь всё потерять?

🔥 ПОСЛЕДНИЙ ШАНС:
Продли прямо сейчас и получи:
• Скидку 30% (промокод: URGENT30)
• +5 дней в подарок
• Персональный план подготовки

До ЕГЭ {days_to_ege} {days_word}!""",
        buttons=[
            {"text": "🚨 Продлить URGENT30", "callback_data": "subscribe_start"},
            {"text": "🔄 Автопродление (выгоднее)", "callback_data": "enable_auto_renew"}
        ]
    )
}

# ==================== CANCELLED СЕГМЕНТ ====================

CANCELLED_TEMPLATES = {
    NotificationTrigger.CANCELLED_DAY1: NotificationTemplate(
        text="""💔 Жаль, что ты ушёл, {first_name}

Мы понимаем - подготовка к ЕГЭ это стресс.

Может мы что-то сделали не так?
Напиши нам, мы обязательно улучшимся!
@obshestvonapalcahsupport

Твой прогресс остаётся с тобой:
📊 {answered_total} заданий решено
📈 Виден рост!

Бесплатная тестовая часть всегда доступна.
Возвращайся когда будешь готов! 💪""",
        buttons=[
            {"text": "📝 Продолжить бесплатно", "callback_data": "to_main_menu"},
            {"text": "💬 Написать в поддержку", "url": "https://t.me/obshestvonapalcahsupport"}
        ]
    ),

    NotificationTrigger.CANCELLED_DAY3: NotificationTemplate(
        text="""🤔 {first_name}, ты уверен в решении?

Из учеников, которые ушли а потом вернулись,
87% говорят: "Зря потерял время"

Факты:
• Твой прогресс был отличным
• Ты знаешь, что бот помогает
• До ЕГЭ {days_to_ege} {days_word}

🎁 Специальное предложение ТОЛЬКО ДЛЯ ТЕБЯ:
Вернись и получи 40% скидку на месяц

Промокод: RETURN40
(действует 3 дня)""",
        buttons=[
            {"text": "🎁 Активировать RETURN40", "callback_data": "subscribe_start"},
            {"text": "🆓 Продолжить бесплатно", "callback_data": "to_main_menu"}
        ]
    ),

    NotificationTrigger.CANCELLED_DAY7: NotificationTemplate(
        text="""⚡ {first_name}, последний шанс вернуться!

За неделю без подготовки:
• Другие прошли 50+ тем
• Многие улучшили баллы на 10-15 пунктов
• Ты потерял темп

До ЕГЭ {days_to_ege} {days_word}.
Каждый день на вес золота!

🔥 СУПЕР-ПРЕДЛОЖЕНИЕ:
50% скидка + бонусные материалы

Промокод: LAST50
(действует только сегодня)

Это действительно последнее предложение.
После этого - только полная цена.""",
        buttons=[
            {"text": "🔥 Вернуться LAST50", "callback_data": "subscribe_start"},
            {"text": "❌ Точно не вернусь", "callback_data": "unsubscribe_forever"}
        ]
    )
}


# Сборка всех шаблонов
ALL_TEMPLATES = {
    **BOUNCED_TEMPLATES,
    **CURIOUS_TEMPLATES,
    **ACTIVE_FREE_TEMPLATES,
    **TRIAL_TEMPLATES,
    **PAYING_INACTIVE_TEMPLATES,
    **CHURN_RISK_TEMPLATES,
    **CANCELLED_TEMPLATES
}


def get_template(trigger: NotificationTrigger) -> Optional[NotificationTemplate]:
    """Возвращает шаблон по триггеру"""
    return ALL_TEMPLATES.get(trigger)
