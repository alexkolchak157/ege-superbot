# 🎯 Retention & Engagement System — Документация

## 📊 Обзор

Система автоматической retention построена для повышения вовлечённости и конверсии пользователей бота. Она классифицирует пользователей на 7 сегментов и отправляет персонализированные уведомления в оптимальное время.

### Цели системы:
1. ✅ **Вернуть bounced пользователей** (зарегистрировались, но не начали)
2. ✅ **Реактивировать curious** (попробовали, но забросили)
3. ✅ **Конвертировать active free → paying** (активные бесплатники в платящих)
4. ✅ **Увеличить trial → paid conversion** (пользователи триала в подписчиков)
5. ✅ **Удержать paying users** (платящие, но неактивные)
6. ✅ **Предотвратить churn** (риск отмены подписки)
7. ✅ **Win-back cancelled** (вернуть отменивших подписку)

---

## 🏗️ Архитектура

Система состоит из 3 основных модулей:

### 1. **User Segmentation** (`core/user_segments.py`)
Классифицирует пользователей по сегментам на основе поведения и статуса подписки.

**7 сегментов:**

| Сегмент | Критерии | Приоритет |
|---------|----------|-----------|
| **BOUNCED** | Зарегистрировался, но не решил ни одного вопроса (1-7 дней) | 🔴 Высокий |
| **CURIOUS** | Решил 1-10 вопросов, неактивен 2-14 дней | 🟠 Высокий |
| **ACTIVE_FREE** | Решает 5+ вопросов/неделю, нет подписки, активен 7+ дней | 🟡 Средний |
| **TRIAL_USER** | На пробном периоде | 🟢 Высокий |
| **PAYING_INACTIVE** | Активная подписка, неактивен 3+ дней | 🔵 Средний |
| **CHURN_RISK** | Подписка через 3-7 дней, автопродление OFF, низкая активность | 🔴 Критичный |
| **CANCELLED** | Отменил подписку 1-14 дней назад | 🟠 Высокий |

### 2. **Notification Templates** (`core/notification_templates.py`)
Персонализированные сообщения для каждого сегмента и триггера.

**Ключевые фичи:**
- ✅ Динамические переменные (`{first_name}`, `{answered_total}`, etc.)
- ✅ Автоматический countdown до ЕГЭ (11 июня)
- ✅ Промокоды для win-back кампаний
- ✅ Кнопки с CTA
- ✅ A/B тестирование (можно добавить варианты)

**Примеры промокодов в шаблонах:**
- `TOP20` — скидка 20% для активных бесплатников (day 20)
- `TRIAL20` — скидка 20% для триалистов (2 дня до окончания)
- `LASTDAY25` — скидка 25% для триалистов (1 день до окончания)
- `COMEBACK30` — скидка 30% для expired trial
- `STAY15` — скидка 15% для churn risk (7 дней)
- `SAVE25` — скидка 25% для churn risk (3 дня)
- `URGENT30` — скидка 30% для churn risk (1 день)
- `RETURN40` — скидка 40% для cancelled (день 3)
- `LAST50` — скидка 50% для cancelled (день 7)

### 3. **Notification Scheduler** (TODO — следующий шаг)
Автоматический планировщик отправки уведомлений.

**Что нужно реализовать:**
- Cron job / APScheduler для ежедневной проверки
- Определение правильного времени отправки (16:00-18:00 после школы)
- Rate limiting (не больше 1 уведомления в день)
- Cooldown periods (24 часа между уведомлениями)
- Tracking отправленных уведомлений (таблица `notification_log`)
- Respect "отписаться" (таблица `notification_preferences`)

---

## 📚 Использование

### Классификация пользователя

```python
from core.user_segments import get_segment_classifier, UserSegment

classifier = get_segment_classifier()

# Классифицировать конкретного пользователя
segment = await classifier.classify_user(user_id=123456)

if segment == UserSegment.BOUNCED:
    print("Пользователь зарегистрировался, но не начал")
elif segment == UserSegment.TRIAL_USER:
    print("Пользователь на trial")
# ... и т.д.

# Получить всех пользователей сегмента
bounced_users = await classifier.get_users_by_segment(
    segment=UserSegment.BOUNCED,
    limit=100
)
```

### Отправка уведомления

```python
from core.notification_templates import get_template, NotificationTrigger
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

# Получить шаблон
template = get_template(NotificationTrigger.BOUNCED_DAY1)

# Подготовить переменные
variables = {
    'first_name': 'Александр',
    'answered_total': 5,
    'checks_remaining': 3
}

# Отрендерить текст
text = template.render(variables)

# Создать кнопки
buttons = []
for btn in template.buttons:
    if 'url' in btn:
        buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
    else:
        buttons.append([InlineKeyboardButton(btn['text'], callback_data=btn['callback_data'])])

keyboard = InlineKeyboardMarkup(buttons)

# Отправить
await bot.send_message(
    chat_id=user_id,
    text=text,
    reply_markup=keyboard,
    parse_mode='HTML'
)
```

---

## 🎨 Примеры сообщений

### Bounced (День 1)
```
📚 Привет, Александр!

Заметили, что ты ещё не начал подготовку.
Вот как это работает:

1️⃣ Нажми "📝 Тестовая часть"
2️⃣ Выбери любую тему
3️⃣ Реши 3-5 вопросов

Это займёт всего 5 минут, а ты поймёшь как это круто! 🚀

⏰ До ЕГЭ: 223 дня
Каждый день на счету!

[🚀 Начать прямо сейчас] [🔕 Не беспокоить]
```

### Trial Expiring (1 день)
```
🚨 Александр, ЗАВТРА trial заканчивается!

Через 24 часа ты потеряешь:
❌ Безлимитные AI-проверки
❌ Задания 19-25
❌ Детальную аналитику
❌ Эталонные ответы

Твой прогресс:
📈 47 заданий решено
🎯 Средний балл растёт

Не останавливайся! Продли подписку со скидкой 25%:

🎁 LASTDAY25 — промокод на 25% скидку
(действует только сегодня)

До ЕГЭ 223 дня. Каждый день важен!

[🔥 Активировать LASTDAY25] [❌ Откажусь от подписки]
```

### Cancelled (День 7 - последний шанс)
```
⚡ Александр, последний шанс вернуться!

За неделю без подготовки:
• Другие прошли 50+ тем
• Многие улучшили баллы на 10-15 пунктов
• Ты потерял темп

До ЕГЭ 223 дня.
Каждый день на вес золота!

🔥 СУПЕР-ПРЕДЛОЖЕНИЕ:
50% скидка + бонусные материалы

Промокод: LAST50
(действует только сегодня)

Это действительно последнее предложение.
После этого - только полная цена.

[🔥 Вернуться LAST50] [❌ Точно не вернусь]
```

---

## 🔧 Что нужно доработать

### 1. **Создать таблицы в БД**

```sql
-- Логирование отправленных уведомлений
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    segment TEXT NOT NULL,
    trigger TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    clicked BOOLEAN DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Настройки уведомлений пользователя
CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id INTEGER PRIMARY KEY,
    enabled BOOLEAN DEFAULT 1,
    disabled_at TIMESTAMP NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Индексы для производительности
CREATE INDEX IF NOT EXISTS idx_notification_log_user ON notification_log(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_log_sent ON notification_log(sent_at);
```

### 2. **Создать промокоды**

Нужно создать промокоды для всех кампаний:

```python
# В админке бота или через SQL
promo_codes = [
    ('TOP20', 20),      # 20% скидка для active free
    ('TRIAL20', 20),    # 20% для триалистов
    ('LASTDAY25', 25),  # 25% последний день trial
    ('COMEBACK30', 30), # 30% expired trial
    ('STAY15', 15),     # 15% churn risk
    ('SAVE25', 25),     # 25% churn risk
    ('URGENT30', 30),   # 30% churn risk последний день
    ('RETURN40', 40),   # 40% cancelled день 3
    ('LAST50', 50),     # 50% cancelled день 7
]

for code, discount in promo_codes:
    # Создать через admin_tools или SQL
    await create_promo_code(code, discount_percent=discount, usage_limit=None)
```

### 3. **Реализовать Notification Scheduler**

**Опции:**

**A) APScheduler (рекомендуется)**
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

# Запускать каждый день в 17:00 (после школы)
scheduler.add_job(
    send_retention_notifications,
    trigger='cron',
    hour=17,
    minute=0
)

scheduler.start()
```

**B) Telegram Bot JobQueue**
```python
# В post_init
application.job_queue.run_daily(
    send_retention_notifications,
    time=datetime.time(hour=17, minute=0, second=0)
)
```

**C) External Cron**
```bash
# Добавить в crontab
0 17 * * * /usr/bin/python3 /path/to/send_notifications.py
```

### 4. **Добавить callbacks для кнопок**

Нужно обработать callback_data из уведомлений:

```python
# В app.py или отдельном файле
from telegram import Update
from telegram.ext import CallbackQueryHandler

async def handle_notification_disable(update: Update, context):
    """Отключить уведомления"""
    user_id = update.effective_user.id

    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            INSERT OR REPLACE INTO notification_preferences (user_id, enabled, disabled_at)
            VALUES (?, 0, ?)
        """, (user_id, datetime.now(timezone.utc)))
        await db.commit()

    await update.callback_query.answer("Уведомления отключены")
    await update.callback_query.edit_message_text(
        "✅ Уведомления отключены.\n\n"
        "Ты можешь включить их в любой момент в настройках."
    )

# Регистрация
application.add_handler(CallbackQueryHandler(
    handle_notification_disable,
    pattern="^notifications_disable$"
))
```

### 5. **Улучшить систему промокодов**

**Текущие проблемы:**
- ✅ Нет автоматического применения промокода из кнопки
- ✅ Нет времени действия промокода (expires_at)
- ✅ Нет персональных промокодов (только для конкретного user_id)

**Предложения:**
```sql
-- Добавить поля в promo_codes
ALTER TABLE promo_codes ADD COLUMN expires_at TIMESTAMP NULL;
ALTER TABLE promo_codes ADD COLUMN user_id INTEGER NULL; -- NULL = для всех
ALTER TABLE promo_codes ADD COLUMN campaign TEXT NULL; -- например "trial_winback"
```

---

## 📊 Рекомендуемый план запуска

### Фаза 1: Тестирование (1 неделя)
1. ✅ Создать промокоды
2. ✅ Создать таблицы БД
3. ✅ Реализовать базовый scheduler
4. ✅ Протестировать на небольшой группе (50-100 пользователей)
5. ✅ Собрать метрики: open rate, click rate, conversion rate

### Фаза 2: Мягкий запуск (2 недели)
1. ✅ Запустить для сегментов TRIAL и CHURN_RISK (наиболее критичные)
2. ✅ Оптимизировать время отправки на основе метрик
3. ✅ A/B тестирование текстов сообщений
4. ✅ Расширить на остальные сегменты

### Фаза 3: Полный запуск
1. ✅ Включить все сегменты
2. ✅ Автоматизировать создание промокодов
3. ✅ Добавить аналитику в админку
4. ✅ Масштабировать на всех пользователей

---

## 📈 Ожидаемые результаты

| Метрика | До | После (прогноз) | Рост |
|---------|-----|-----------------|------|
| **7-day retention** | ~10% | 40%+ | **+300%** |
| **Trial → Paid** | <5% | 15-20% | **+300-400%** |
| **Churn rate** | ~70% | 40-50% | **-30-40%** |
| **LTV** | ~350₽ | ~550₽ | **+57%** |
| **Активные пользователи** | Единицы | 30-40% из 300 | **10x** |

---

## 🎯 Следующие шаги

**Что делать прямо сейчас:**

1. **Создай промокоды через админку** — `/create_promo` (если есть команда)

2. **Создай таблицы БД** — выполни SQL из раздела "Доработки"

3. **Протестируй классификацию** — проверь на нескольких пользователях:
   ```python
   # В Python console или через /test_retention
   from core.user_segments import get_segment_classifier

   classifier = get_segment_classifier()
   segment = await classifier.classify_user(YOUR_USER_ID)
   print(f"Сегмент: {segment}")
   ```

4. **Отправь тестовое уведомление** — вручную проверь как выглядят сообщения

5. **Реализуй scheduler** — начни с простого cron job или JobQueue

---

## 💡 Советы по оптимизации

### Персонализация
- Используй имя пользователя (`{first_name}`)
- Показывай реальный прогресс (`{answered_total}`)
- Динамический countdown до ЕГЭ (автоматически)

### Timing
- **Лучшее время:** 16:00-18:00 (после школы)
- **Никогда:** ночью (00:00-07:00)
- **Частота:** не более 1 уведомления в день

### CTA
- Всегда 1-2 чёткие кнопки действия
- Использовать scarcity ("только сегодня", "последний шанс")
- Показывать value ("получи скидку 50%", "экономия 125₽")

### A/B тестирование
- Тестируй 2-3 варианта текста для каждого триггера
- Измеряй: open rate, click rate, conversion rate
- Побеждает тот вариант который даёт больше conversions (не кликов!)

---

## 🆘 Поддержка и вопросы

Если что-то непонятно или нужна помощь с реализацией:
1. Проверь эту документацию
2. Посмотри примеры в коде (`core/user_segments.py`, `core/notification_templates.py`)
3. Спроси в issues GitHub

**Удачи с повышением retention! 🚀**
