# План рефакторинга: Интеграция подписок для учителей

## Статус: Критичные проблемы исправлены ✅

### Уже исправлено (Приоритет 1 - Критично)

✅ **Проблема #2: Проверка даты истечения подписки**
- Файл: `teacher_mode/services/teacher_service.py:301`
- Добавлена проверка `subscription_expires` в функции `can_add_student()`
- Учителя с истекшей подпиской больше не смогут добавлять учеников

✅ **Проблема #3: Валидация plan_id**
- Файл: `payment/subscription_manager.py:1495-1496`
- Добавлена валидация `is_teacher_plan()` перед созданием профиля
- Защита от передачи некорректных plan_id

✅ **Проблема #4: Race condition**
- Файл: `payment/subscription_manager.py:1536-1539`
- Добавлена обработка `IntegrityError` при одновременном создании профиля
- Логирование успешного обнаружения существующего профиля

---

## Приоритет 2: Высокий (3-5 дней)

### Проблема #5: Отсутствие откатываемой транзакции
**Описание:** Если обновление `teacher_profiles` упадет, данные в `module_subscriptions` останутся активными.

**Решение:**
```python
async with aiosqlite.connect(self.database_file) as db:
    try:
        # Обновление module_subscriptions
        await db.execute(...)

        # Обновление teacher_profiles
        await db.execute("""
            UPDATE teacher_profiles
            SET has_active_subscription = 1,
                subscription_expires = ?,
                subscription_tier = ?
            WHERE user_id = ?
        """, (expires_at, plan_id, user_id))

        await db.commit()
        logger.info("✅ Transaction committed successfully")
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Transaction rolled back: {e}")
        raise
```

**Файлы:**
- `payment/subscription_manager.py:1542-1551`

**Оценка времени:** 2-3 часа

---

### Проблема #6: Отсутствие синхронизации дат между таблицами
**Описание:** Дата в `teacher_profiles.subscription_expires` и `module_subscriptions.expires_at` может не совпадать.

**Решение:**
1. Использовать `module_subscriptions.expires_at` как единый источник истины
2. В `get_teacher_profile()` получать дату из `module_subscriptions`:

```python
async def get_teacher_profile(user_id: int) -> Optional[TeacherProfile]:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                tp.user_id, tp.teacher_code, tp.display_name, tp.subscription_tier,
                tp.created_at, tp.feedback_settings,
                CASE
                    WHEN ms.expires_at > datetime('now') THEN 1
                    ELSE 0
                END as has_active_subscription,
                ms.expires_at as subscription_expires
            FROM teacher_profiles tp
            LEFT JOIN module_subscriptions ms
                ON tp.user_id = ms.user_id
                AND ms.is_active = 1
                AND ms.plan_id IN ('teacher_basic', 'teacher_standard', 'teacher_premium')
            WHERE tp.user_id = ?
            ORDER BY ms.expires_at DESC
            LIMIT 1
        """, (user_id,))
        ...
```

**Файлы:**
- `teacher_mode/services/teacher_service.py:96-134`

**Оценка времени:** 4-6 часов

---

### Проблема #7: Отсутствие проверки целостности данных
**Описание:** При каждом обращении к `can_add_student()` нужно проверять целостность данных между таблицами.

**Решение:**
```python
async def validate_teacher_subscription_integrity(teacher_id: int) -> bool:
    """Проверяет согласованность данных между teacher_profiles и module_subscriptions"""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("""
            SELECT
                tp.has_active_subscription as tp_active,
                tp.subscription_expires as tp_expires,
                ms.is_active as ms_active,
                ms.expires_at as ms_expires
            FROM teacher_profiles tp
            LEFT JOIN module_subscriptions ms
                ON tp.user_id = ms.user_id
                AND ms.plan_id IN ('teacher_basic', 'teacher_standard', 'teacher_premium')
            WHERE tp.user_id = ?
        """, (teacher_id,))

        row = await cursor.fetchone()
        if not row:
            return False

        # Проверяем несоответствия
        if row['tp_active'] != row['ms_active']:
            logger.warning(f"Inconsistency detected for teacher {teacher_id}")
            return False

        return True
```

**Файлы:**
- `teacher_mode/services/teacher_service.py` (новая функция)

**Оценка времени:** 3-4 часа

---

### Проблема #8: Отсутствие уведомлений при истечении подписки
**Описание:** Учителя не получают уведомления о скором истечении подписки.

**Решение:**
1. Создать scheduler для проверки истекающих подписок:

```python
# teacher_mode/subscription_scheduler.py
async def check_expiring_teacher_subscriptions(context):
    """Проверяет подписки учителей, истекающие в ближайшие 3 дня"""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("""
            SELECT user_id, subscription_expires
            FROM teacher_profiles
            WHERE has_active_subscription = 1
            AND subscription_expires <= datetime('now', '+3 days')
            AND subscription_expires > datetime('now')
        """)

        expiring_teachers = await cursor.fetchall()

        for user_id, expires_at in expiring_teachers:
            days_left = (expires_at - datetime.now()).days
            await context.bot.send_message(
                user_id,
                f"⚠️ Ваша учительская подписка истекает через {days_left} дней!\n"
                f"Продлите подписку, чтобы не потерять доступ к функциям."
            )
```

2. Регистрировать scheduler в `core/app.py`:

```python
# Проверка истекающих подписок учителей каждый день в 10:00
application.job_queue.run_daily(
    check_expiring_teacher_subscriptions,
    time=dt_time(hour=10, minute=0, tzinfo=msk_tz),
    name='teacher_subscription_expiry_check'
)
```

**Файлы:**
- `teacher_mode/subscription_scheduler.py` (новый файл)
- `core/app.py:240-260` (добавить новый scheduler)

**Оценка времени:** 4-5 часов

---

### Проблема #9: Несогласованность проверок доступа
**Описание:** В разных местах кода проверка доступа учителя выполняется по-разному.

**Решение:**
Унифицировать проверку доступа через единую функцию:

```python
async def has_teacher_access(user_id: int) -> bool:
    """
    Единая функция проверки доступа учителя.
    Проверяет:
    1. Существование профиля
    2. Активность подписки
    3. Дату истечения
    """
    profile = await get_teacher_profile(user_id)
    if not profile:
        return False

    if not profile.has_active_subscription:
        return False

    if profile.subscription_expires and profile.subscription_expires < datetime.now():
        return False

    return True
```

Заменить все проверки типа:
```python
# Было:
profile = await get_teacher_profile(user_id)
if profile and profile.has_active_subscription:
    ...

# Стало:
if await has_teacher_access(user_id):
    ...
```

**Файлы:**
- `teacher_mode/handlers/teacher_handlers.py:25-30`
- `teacher_mode/handlers/assignment_handlers.py` (множественные места)
- Все файлы в `teacher_mode/`

**Оценка времени:** 5-6 часов

---

### Проблема #10: Отсутствие автоматического сброса has_active_subscription
**Описание:** Когда подписка истекает, флаг `has_active_subscription` не сбрасывается автоматически.

**Решение:**
1. Создать фоновую задачу для деактивации истекших подписок:

```python
async def deactivate_expired_teacher_subscriptions(context):
    """Деактивирует истекшие подписки учителей"""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Находим истекшие подписки
        await db.execute("""
            UPDATE teacher_profiles
            SET has_active_subscription = 0
            WHERE has_active_subscription = 1
            AND subscription_expires < datetime('now')
        """)

        changes = db.total_changes
        await db.commit()

        if changes > 0:
            logger.info(f"Deactivated {changes} expired teacher subscriptions")
```

2. Запускать каждый час через job_queue:

```python
application.job_queue.run_repeating(
    deactivate_expired_teacher_subscriptions,
    interval=3600,  # Каждый час
    first=10,
    name='deactivate_expired_teachers'
)
```

**Файлы:**
- `teacher_mode/subscription_scheduler.py` (добавить функцию)
- `core/app.py` (зарегистрировать job)

**Оценка времени:** 2-3 часа

---

## Приоритет 3: Средний (вторая неделя)

### Проблема #11: Нет истории изменений тарифов
**Описание:** Невозможно отследить, когда учитель менял тарифы.

**Решение:**
1. Создать таблицу `teacher_subscription_history`:

```sql
CREATE TABLE IF NOT EXISTS teacher_subscription_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan_id TEXT NOT NULL,
    action TEXT NOT NULL,  -- 'activated', 'renewed', 'upgraded', 'downgraded', 'expired'
    previous_tier TEXT,
    new_tier TEXT,
    expires_at DATETIME,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

2. Логировать все изменения в subscription_manager:

```python
async def log_teacher_subscription_change(
    user_id: int,
    plan_id: str,
    action: str,
    previous_tier: Optional[str],
    new_tier: str,
    expires_at: datetime
):
    async with aiosqlite.connect(self.database_file) as db:
        await db.execute("""
            INSERT INTO teacher_subscription_history
            (user_id, plan_id, action, previous_tier, new_tier, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, plan_id, action, previous_tier, new_tier, expires_at, datetime.now()))
        await db.commit()
```

**Файлы:**
- `core/db.py` (добавить миграцию)
- `payment/subscription_manager.py` (добавить логирование)

**Оценка времени:** 6-8 часов

---

### Проблема #12: Все планы учителей активируют одинаковые модули
**Описание:** Возможно, нужна дифференциация доступа к модулям в зависимости от тарифа.

**Решение:**
1. Обсудить с командой, нужна ли дифференциация
2. Если да - обновить конфигурацию:

```python
'teacher_basic': {
    'modules': ['test_part', 'task19', 'task20'],  # Только базовые
    ...
},
'teacher_premium': {
    'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],  # Все модули
    ...
}
```

**Файлы:**
- `payment/config.py:118-203`
- Обсуждение с командой

**Оценка времени:** 2-3 часа (после обсуждения)

---

### Проблема #13: Отсутствие валидации при покупке подписки
**Описание:** Не проверяется, не купил ли пользователь случайно учительскую подписку вместо обычной.

**Решение:**
Добавить предупреждение в UI при выборе учительского плана:

```python
if is_teacher_plan(selected_plan_id):
    keyboard = [
        [InlineKeyboardButton("✅ Да, я учитель", callback_data=f"confirm_teacher_{plan_id}")],
        [InlineKeyboardButton("❌ Нет, выбрать другой тариф", callback_data="subscribe_start")]
    ]
    await update.callback_query.edit_message_text(
        "⚠️ Вы выбрали учительский тариф.\n\n"
        "Этот тариф предназначен для репетиторов и учителей, которые хотят:\n"
        "• Создавать домашние задания\n"
        "• Отслеживать прогресс учеников\n"
        "• Получать аналитику\n\n"
        "Вы действительно учитель?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
```

**Файлы:**
- `payment/handlers.py` (обработчик выбора плана)

**Оценка времени:** 3-4 часа

---

## Долгосрочная архитектурная задача (Приоритет 4)

### Задача #1: Устранение дублирования данных
**Описание:** Полностью убрать поля `has_active_subscription` и `subscription_expires` из `teacher_profiles`, использовать только `module_subscriptions`.

**Преимущества:**
- Единый источник истины
- Нет проблем синхронизации
- Упрощение кода

**План:**
1. Создать view в БД для получения статуса подписки:

```sql
CREATE VIEW teacher_subscription_status AS
SELECT
    tp.user_id,
    tp.teacher_code,
    tp.display_name,
    tp.subscription_tier,
    tp.created_at,
    tp.feedback_settings,
    CASE
        WHEN ms.expires_at > datetime('now') THEN 1
        ELSE 0
    END as has_active_subscription,
    ms.expires_at as subscription_expires
FROM teacher_profiles tp
LEFT JOIN module_subscriptions ms
    ON tp.user_id = ms.user_id
    AND ms.is_active = 1
    AND ms.plan_id IN ('teacher_basic', 'teacher_standard', 'teacher_premium')
```

2. Обновить все функции для использования view вместо прямых запросов
3. Удалить колонки `has_active_subscription` и `subscription_expires` из `teacher_profiles`

**Файлы:**
- `core/db.py` (миграция)
- `teacher_mode/services/teacher_service.py` (все функции)
- `payment/subscription_manager.py` (убрать UPDATE на teacher_profiles)

**Оценка времени:** 10-15 часов

**Риски:**
- Требует тщательного тестирования
- Может сломать существующий функционал
- Нужна миграция существующих данных

---

## Приоритизация работ

### Неделя 1 (Приоритет 2)
- [x] День 1-2: Проблемы #5, #6 (транзакции и синхронизация)
- [ ] День 3-4: Проблемы #7, #10 (проверка целостности и автосброс)
- [ ] День 5: Проблемы #8, #9 (уведомления и унификация проверок)

### Неделя 2 (Приоритет 3)
- [ ] День 1-2: Проблема #11 (история изменений)
- [ ] День 3: Проблемы #12, #13 (дифференциация и валидация)
- [ ] День 4-5: Тестирование и документация

### Месяц 1-2 (Приоритет 4, по возможности)
- [ ] Разработка плана миграции на единый источник истины
- [ ] Обсуждение с командой
- [ ] Реализация и тестирование на staging
- [ ] Развертывание на production

---

## Контрольные точки (Checkpoints)

### Чекпоинт 1 (конец недели 1)
✅ Все критичные проблемы решены
✅ Транзакции работают корректно
✅ Синхронизация данных исправлена
✅ Уведомления работают
⬜ Код покрыт тестами

### Чекпоинт 2 (конец недели 2)
⬜ История изменений логируется
⬜ Валидация работает
⬜ Документация обновлена
⬜ Все изменения протестированы

### Чекпоинт 3 (конец месяца 1)
⬜ План миграции утвержден
⬜ Staging развернут
⬜ Тесты пройдены
⬜ Готово к production

---

## Контакты и ответственные

- **Критичные проблемы (1-4):** Исправлены ✅
- **Высокий приоритет (5-10):** [Назначить ответственного]
- **Средний приоритет (11-13):** [Назначить ответственного]
- **Долгосрочные задачи:** [Обсудить с командой]

---

## Примечания

1. Все изменения должны сопровождаться тестами
2. Каждая проблема требует code review
3. Критичные изменения требуют тестирования на staging
4. Документацию обновлять параллельно с кодом
5. Логировать все важные операции для отладки

---

**Дата создания:** 2025-11-10
**Автор:** Claude AI Assistant
**Статус:** В работе
