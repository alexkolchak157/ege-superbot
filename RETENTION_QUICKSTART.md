# 🚀 Retention System — Quick Start

Краткая инструкция по запуску retention системы для EGE Bot.

## ✅ Что уже реализовано

### Этап 1: Базовая инфраструктура (✅ ЗАВЕРШЁН)

**Модули:**
- ✅ `core/user_segments.py` — Классификация пользователей на 7 сегментов
- ✅ `core/notification_templates.py` — 17 триггеров уведомлений с промокодами
- ✅ `core/retention_scheduler.py` — Автоматический планировщик отправки
- ✅ `core/notification_handlers.py` — Обработчики callback-кнопок
- ✅ `core/migrations/add_retention_system.sql` — SQL миграция
- ✅ `scripts/create_retention_promo_codes.py` — Автогенерация промокодов
- ✅ Интеграция в `core/app.py` — Job Queue (17:00 ежедневно)
- ✅ Трекинг конверсий в `payment/webhook.py`

**Файлы документации:**
- ✅ `RETENTION_SYSTEM.md` — Полная документация
- ✅ `RETENTION_QUICKSTART.md` — Этот файл

---

## 📋 Шаги для запуска

### Шаг 1: Применить SQL миграцию

```bash
cd /home/user/ege-superbot

# Применить миграцию
python -c "
import sqlite3
conn = sqlite3.connect('quiz_async.db')
with open('core/migrations/add_retention_system.sql', 'r') as f:
    conn.executescript(f.read())
conn.commit()
conn.close()
print('✅ Миграция применена')
"

# Проверить созданные таблицы
sqlite3 quiz_async.db ".tables" | grep notification
```

**Ожидаемый вывод:**
```
notification_cooldown  notification_log  notification_preferences
```

### Шаг 2: Создать промокоды

```bash
# Запустить скрипт генерации промокодов
python scripts/create_retention_promo_codes.py
```

**Ожидаемый вывод:**
```
============================================================
🎁 СОЗДАНИЕ ПРОМОКОДОВ ДЛЯ RETENTION-СИСТЕМЫ
============================================================

📂 База данных: quiz_async.db
📊 Промокодов к созданию: 9

  ✅ TOP20 создан (20% скидка)
  ✅ TRIAL20 создан (20% скидка)
  ✅ LASTDAY25 создан (25% скидка)
  ✅ COMEBACK30 создан (30% скидка)
  ✅ STAY15 создан (15% скидка)
  ✅ SAVE25 создан (25% скидка)
  ✅ URGENT30 создан (30% скидка)
  ✅ RETURN40 создан (40% скидка)
  ✅ LAST50 создан (50% скидка)

============================================================
✅ Готово!
   Создано: 9
   Пропущено (уже существуют): 0
============================================================
```

### Шаг 3: Запустить бота

```bash
# Бот уже настроен! Просто запустите его:
python bot.py
```

**В логах вы должны увидеть:**
```
[INFO] Notification handlers registered
[INFO] Retention scheduler initialized and scheduled for 17:00 daily
```

### Шаг 4: (Опционально) Протестировать вручную

Если хотите протестировать без ожидания 17:00:

```python
# В Python console
import asyncio
from core.retention_scheduler import get_retention_scheduler
from telegram import Bot

async def test():
    bot = Bot(token="YOUR_BOT_TOKEN")
    scheduler = get_retention_scheduler()

    # Тестируем классификацию
    from core.user_segments import get_segment_classifier
    classifier = get_segment_classifier()

    # Подставьте реальный user_id
    segment = await classifier.classify_user(123456789)
    print(f"Segment: {segment}")

    # Получить активность
    activity = await classifier.get_user_activity_stats(123456789)
    print(f"Activity: {activity}")

asyncio.run(test())
```

---

## 📊 Проверка работы системы

### Проверить созданные промокоды

```bash
sqlite3 quiz_async.db "SELECT code, discount_percent, description FROM promo_codes WHERE code LIKE '%20' OR code LIKE '%25' OR code LIKE '%30' OR code LIKE '%40' OR code LIKE '%50';"
```

### Проверить статистику уведомлений (после отправки)

```bash
# Общая статистика по сегментам
sqlite3 quiz_async.db "SELECT * FROM notification_stats_by_segment;"

# Дневная статистика
sqlite3 quiz_async.db "SELECT * FROM notification_stats_daily ORDER BY date DESC LIMIT 7;"

# Топ промокодов
sqlite3 quiz_async.db "SELECT * FROM notification_promo_performance ORDER BY conversion_rate DESC;"
```

### Проверить отправленные уведомления

```bash
sqlite3 quiz_async.db "
SELECT
    user_id,
    segment,
    trigger,
    clicked,
    converted,
    promo_code,
    datetime(sent_at, 'localtime') as sent_at
FROM notification_log
ORDER BY sent_at DESC
LIMIT 10;
"
```

---

## 🔧 Настройка и кастомизация

### Изменить время отправки

По умолчанию: 17:00 (после школы).

Изменить в `core/app.py` строку 180:

```python
# Было:
time=dt_time(hour=17, minute=0, second=0),

# Изменить на, например, 18:30:
time=dt_time(hour=18, minute=30, second=0),
```

### Изменить лимиты отправки

По умолчанию: 1 уведомление в день, 3 в неделю.

Изменить в `core/retention_scheduler.py` строка 63:

```python
if count_row and count_row[0] >= 1:  # Было: 1 в день
    return False, "daily_limit_exceeded"

# Изменить на, например, 2 в день:
if count_row and count_row[0] >= 2:
```

### Изменить тексты уведомлений

Все шаблоны в `core/notification_templates.py`.

Пример изменения:

```python
NotificationTemplate(
    trigger=NotificationTrigger.BOUNCED_DAY1,
    text=(
        "📚 Привет, {first_name}!\n\n"
        "Ваш новый текст здесь...\n"
    ),
    buttons=[...]
)
```

---

## 🎯 Ожидаемые результаты

После запуска системы (1-2 недели):

| Метрика | До | После (прогноз) |
|---------|-----|-----------------|
| **7-day retention** | ~10% | 40%+ |
| **Trial → Paid** | <5% | 15-20% |
| **Churn rate** | ~70% | 40-50% |
| **Активные пользователи** | Единицы | 30-40% из 300 |

---

## 🐛 Troubleshooting

### Уведомления не отправляются

**Проверьте:**

1. **Job Queue запущена?**
   ```bash
   # В логах должно быть:
   grep "Retention scheduler initialized" logs/bot.log
   ```

2. **Есть ли пользователи в сегментах?**
   ```python
   from core.user_segments import get_segment_classifier, UserSegment

   classifier = get_segment_classifier()
   bounced = await classifier.get_users_by_segment(UserSegment.BOUNCED, limit=10)
   print(f"Bounced users: {len(bounced)}")
   ```

3. **Проверьте таблицу notification_preferences:**
   ```bash
   sqlite3 quiz_async.db "SELECT COUNT(*) FROM notification_preferences WHERE enabled = 0;"
   # Если много отключенных, проверьте причину:
   sqlite3 quiz_async.db "SELECT disabled_reason, COUNT(*) FROM notification_preferences WHERE enabled = 0 GROUP BY disabled_reason;"
   ```

### Ошибки при запуске бота

**Если `ImportError`:**

```bash
# Проверьте что все файлы на месте:
ls -la core/retention_scheduler.py
ls -la core/notification_handlers.py
ls -la core/user_segments.py
ls -la core/notification_templates.py
```

**Если ошибка SQL:**

```bash
# Убедитесь что миграция применена:
sqlite3 quiz_async.db ".schema notification_log"
```

---

## 📞 Поддержка

Полная документация: `RETENTION_SYSTEM.md`

Если что-то не работает:
1. Проверьте логи: `tail -f logs/bot.log | grep -i retention`
2. Проверьте БД: `sqlite3 quiz_async.db`
3. Откройте issue на GitHub

---

## 🎉 Следующие шаги (Этап 2)

После успешного запуска Этапа 1:

1. **Собрать метрики за 1-2 недели**
   - Click rate, conversion rate по сегментам
   - Оптимизировать тексты уведомлений

2. **A/B тестирование**
   - Тестировать разные варианты текстов
   - Оптимизировать время отправки

3. **Расширенная аналитика**
   - Dashboard для мониторинга
   - Автоматические отчёты

4. **Персонализация промокодов**
   - Промокоды с ограниченным сроком действия
   - Персональные промокоды для VIP-пользователей

**Удачи! 🚀**
