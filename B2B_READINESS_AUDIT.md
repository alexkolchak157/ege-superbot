# Аудит готовности к B2B-распространению

**Дата:** 2026-03-01
**Область:** Модуль учителя (`teacher_mode/`) + Быстрая проверка (все виды) + B2B API (`b2b_api/`)

---

## Оглавление

1. [Резюме](#1-резюме)
2. [Архитектура модуля учителя](#2-архитектура-модуля-учителя)
3. [Быстрая проверка — все виды](#3-быстрая-проверка--все-виды)
4. [B2B API](#4-b2b-api)
5. [Критические проблемы](#5-критические-проблемы)
6. [Серьезные проблемы](#6-серьезные-проблемы)
7. [Средние проблемы](#7-средние-проблемы)
8. [Рекомендации по приоритетам](#8-рекомендации-по-приоритетам)

---

## 1. Резюме

### Общая оценка: **НЕ ГОТОВ к B2B-распространению**

| Категория | Оценка | Статус |
|-----------|--------|--------|
| Функциональность teacher_mode | 8/10 | Хорошо |
| Быстрая проверка (task17-25) | 8/10 | Хорошо |
| B2B API (функциональность) | 7/10 | Удовлетворительно |
| Безопасность | 4/10 | **Критично** |
| Изоляция данных / multi-tenancy | 3/10 | **Критично** |
| Масштабируемость | 2/10 | **Критично** |
| Биллинг B2B | 2/10 | **Критично** |
| Тестирование | 2/10 | **Критично** |
| Мониторинг / observability | 3/10 | **Критично** |
| Документация API | 6/10 | Удовлетворительно |

**Блокирующих проблем:** 5
**Серьезных проблем:** 7
**Средних проблем:** 6

---

## 2. Архитектура модуля учителя

### 2.1 Структура (хорошо)

```
teacher_mode/
├── models.py              # Dataclass-модели: TeacherProfile, QuickCheck, QuickCheckQuota
├── states.py              # FSM-состояния (ConversationHandler)
├── plugin.py              # Плагин для регистрации в ботe
├── handlers/
│   ├── teacher_handlers.py    # CRUD учителей, управление учениками
│   ├── student_handlers.py    # Интерфейс ученика
│   ├── quick_check_handlers.py # Быстрая проверка (UI в Telegram)
│   ├── variant_check_handlers.py # Проверка вариантов целиком
│   └── analytics_handlers.py  # Аналитика и статистика
├── services/
│   ├── teacher_service.py     # Бизнес-логика учителей
│   ├── quick_check_service.py # Логика быстрой проверки + квоты
│   ├── variant_check_service.py # Сохранение проверок вариантов
│   ├── ai_homework_evaluator.py # AI-проверка (маршрутизация по типам)
│   ├── assignment_service.py  # Домашние задания
│   ├── analytics_service.py   # Аналитика
│   ├── notification_service.py # Уведомления
│   └── gift_service.py        # Подарки и промокоды
├── utils/
│   ├── validation.py          # Валидация ввода
│   ├── rate_limiter.py        # Ограничение операций
│   └── datetime_utils.py      # Timezone-aware даты
└── migrations/                # SQL-миграции
```

**Плюсы:**
- Чистая плагинная архитектура (`plugin_base.py`)
- Хорошее разделение на модели / сервисы / хендлеры
- Enum-типы для статусов и ролей
- Timezone-aware даты через утилиту `utc_now()`
- Защита от race conditions через `BEGIN EXCLUSIVE` транзакции

**Минусы:**
- Жесткая привязка к Telegram (нет абстракции транспорта)
- Дублирование функции `_safe_json_loads()` в нескольких сервисах
- Каждый метод сервиса создает свое соединение с БД (`aiosqlite.connect()`)

### 2.2 Подписки учителей

| Тариф | Цена | Учеников | Быстрых проверок/мес |
|-------|------|----------|---------------------|
| Free | 0 руб. | 1 | 50 |
| Basic | 249 руб. | 10 | 100 |
| Standard | 449 руб. | 20 | 500 |
| Premium | 699 руб. | Безлимит | 2000 |

**Проблема:** Эти тарифы предназначены для индивидуальных учителей в Telegram.
Для B2B (онлайн-школ) нужна совершенно другая тарифная сетка,
которая определена в B2B API через `ClientTier` (Free → Enterprise).
Два мира подписок существуют параллельно без интеграции.

---

## 3. Быстрая проверка — все виды

### 3.1 Покрытие типов заданий

| Задание | Evaluator | Freeform | B2B API | Пакетный режим |
|---------|-----------|----------|---------|----------------|
| task17 | `Task17AIEvaluator` | Нет | Нет | Да |
| task18 | `Task18AIEvaluator` | Нет | Нет | Да |
| task19 | `Task19AIEvaluator` | Нет | Да | Да |
| task20 | `Task20AIEvaluator` | Нет | Да | Да |
| task21 | `Task21Evaluator` + freeform | Да (AI) | Да | Да |
| task22 | `Task22AIEvaluator` + freeform | Да (AI) | Да | Да |
| task23 | `Task23Evaluator` | Нет | Да | Да |
| task24 | `evaluate_plan_with_ai` | Нет | Да | Да |
| task25 | `Task25AIEvaluator` | Нет | Да | Да |
| custom | Маршрутизация по типу | — | Нет | Нет |

**Проблема:** B2B API поддерживает только task19-25, но teacher_mode уже поддерживает
task17, task18 и custom. Несоответствие функциональности.

### 3.2 Проверка вариантов целиком (`variant_check_handlers.py`)

- Поддерживает все 25 заданий (1-16 тестовая часть + 17-25 развернутые)
- Пакетный режим до 30 учеников
- Источники: вариант из бота, внешний вариант, загрузка ключей из файлов/фото
- Расчет первичных и вторичных баллов, оценка по шкале

**Плюсы:**
- Богатый функционал, покрывающий реальные потребности учителей
- Поддержка загрузки ответов и условий из фото (OCR через Claude Vision)
- Сохранение истории проверок

**Минусы:**
- Функционал привязан к Telegram UI, нет REST API для проверки вариантов
- Таблица `variant_checks` создается динамически (`ensure_tables()`)

### 3.3 Квотная система

```python
_get_monthly_limit_by_tier():
    'teacher_basic': 100
    'teacher_standard': 500
    'teacher_premium': 2000
    default: 50
```

- Месячные периоды (30 дней)
- Бонусные проверки (не сгорают)
- Атомарная проверка и списание через транзакции

**Проблема:** Квоты teacher_mode и B2B API — две независимые системы.
При B2B-распространении нужна единая система учета.

---

## 4. B2B API

### 4.1 Архитектура (удовлетворительно)

```
b2b_api/
├── app.py                    # FastAPI, middleware, CORS
├── middleware/
│   ├── api_key_auth.py       # Авторизация по API-ключу
│   └── rate_limiter.py       # Rate limiting (minute/daily/monthly)
├── routes/
│   ├── check.py              # POST /check, GET /check/{id}, GET /checks
│   ├── questions.py          # GET /questions, GET /questions/{id}, GET /questions/stats
│   └── client.py             # GET /me, GET /usage, GET /limits
├── schemas/
│   ├── check.py              # Pydantic: CheckRequest, CheckResponse, CriteriaScore
│   ├── client.py             # Pydantic: B2BClient, ClientTier, UsageStats
│   └── questions.py          # Pydantic: B2BQuestion
├── services/
│   └── api_logger.py         # Batch API logger
└── migrations/
    ├── b2b_tables.sql        # 7 таблиц + 2 views
    └── apply_migration.py
```

### 4.2 Тарифы B2B API

| Tier | RPM | RPD | Месячная квота | Scopes |
|------|-----|-----|----------------|--------|
| Free | 5 | 50 | 100 | check:create/read |
| Trial | 10 | 200 | 500 | + questions:read |
| Basic | 20 | 500 | 2,000 | + questions:read |
| Standard | 30 | 1,000 | 10,000 | + stats:read |
| Premium | 60 | 5,000 | 50,000 | + questions:samples |
| Enterprise | 120 | 20,000 | Безлимит | + admin |

### 4.3 Плюсы

- Хорошая структура FastAPI с middleware-стеком
- Pydantic-схемы с примерами и валидацией
- Swagger UI + ReDoc документация
- API-ключи хешируются (SHA-256) перед хранением
- Rate limiting с sliding window (минуты) и fixed window (дни)
- Scope-based авторизация (check:create, questions:read и т.д.)
- API logging для биллинга (batch insert, каждые 10 сек)
- Поддержка `external_id` для связи с системами клиентов
- Асинхронная обработка проверок через `BackgroundTasks`

---

## 5. Критические проблемы

### CRIT-1: SQLite не подходит для B2B production

**Файлы:** `core/config.py:20`, `core/db.py`, все сервисы

**Проблема:** Вся система использует SQLite как единственное хранилище данных.
SQLite работает как файл на диске, не поддерживает конкурентную запись,
и создает бутылочное горлышко при нескольких одновременных B2B-клиентах.

```python
# core/config.py:20
DATABASE_FILE = os.getenv("DATABASE_FILE", "quiz_async.db")

# Каждый сервис открывает свое соединение:
async with aiosqlite.connect(DATABASE_FILE) as db:
    await db.execute("BEGIN EXCLUSIVE")  # Блокирует ВСЮ базу
```

**Последствия:**
- `BEGIN EXCLUSIVE` блокирует всю БД на время транзакции
- Нет connection pooling — каждый запрос создает/закрывает соединение
- Нет горизонтального масштабирования (один файл = один сервер)
- При 5+ одновременных API-запросах начнутся `database is locked` ошибки

**Решение:** Миграция на PostgreSQL с connection pooling (asyncpg + SQLAlchemy).

---

### CRIT-2: Отсутствие изоляции данных между тенантами

**Файлы:** `b2b_api/routes/check.py`, `b2b_api/migrations/b2b_tables.sql`

**Проблема:** Все B2B-клиенты хранят данные в одних таблицах.
Единственная защита — фильтр `WHERE client_id = ?`.
Ошибка в запросе = утечка данных одного клиента к другому.

```sql
-- Все проверки в одной таблице
SELECT * FROM b2b_checks WHERE client_id = ? AND check_id = ?
-- Если забыть WHERE client_id — утечка данных
```

Также данные teacher_mode (учителя, ученики, задания) и B2B API
хранятся в одной физической БД без какой-либо изоляции.

**Решение:**
- Row-Level Security (PostgreSQL RLS)
- Или schema-per-tenant
- Обязательный audit log доступа к данным

---

### CRIT-3: In-memory состояние — потеря данных при перезапуске

**Файлы:** `b2b_api/middleware/rate_limiter.py`, `b2b_api/services/api_logger.py`, `b2b_api/middleware/api_key_auth.py`

**Проблема:** Критические данные хранятся только в памяти процесса:

| Компонент | Данные в памяти | Последствие потери |
|-----------|-----------------|--------------------|
| `SlidingWindowCounter` | Счетчики запросов/мин | Сброс rate limits |
| `DailyCounter` | Счетчики запросов/день | Обход дневных лимитов |
| `APILogger._queue` | Очередь логов (до 50 записей) | **Потеря данных для биллинга** |
| `APIKeyAuth._cache` | Кэш API-ключей | Нагрузка на БД при рестарте |

```python
# api_logger.py:97 - потеря данных при рестарте
class APILogger:
    def __init__(self):
        self._queue = deque()  # Логи в памяти!
```

**Решение:** Redis для rate limiting, кэша и очередей. Либо WAL-based persistent queue.

---

### CRIT-4: Webhook уведомления НЕ реализованы

**Файл:** `b2b_api/routes/check.py:161`

```python
# TODO: Отправить webhook если указан callback_url
```

API принимает `callback_url` в запросе, таблица `b2b_webhook_deliveries` создана
в миграциях, но сама доставка webhook **не реализована**.
Это обещанный, но несуществующий функционал.

**Решение:** Реализовать webhook delivery с retry-логикой, подписью HMAC,
и таймаутами. Или убрать `callback_url` из API до реализации.

---

### CRIT-5: Отсутствие тестов для B2B API

**Файлы:** `tests/` — содержит только 3 файла, ни один не тестирует B2B API

```
tests/
├── conftest.py                  # Базовая фикстура
├── test_document_processor.py   # 1 тест
├── test_hint_manager.py         # Тесты hint manager
└── test_teacher_payment.py      # Тесты подписок учителей
```

- **0 тестов** для B2B API endpoints
- **0 тестов** для rate limiting
- **0 тестов** для API key auth
- **0 тестов** для AI evaluators в контексте B2B
- `test_teacher_mode.py` — только import/model smoke tests (не pytest)

**Решение:** Минимум: unit-тесты для auth, rate limiting, API endpoints.
Integration тесты для полного flow: создание клиента → ключ → проверка → результат.

---

## 6. Серьезные проблемы

### HIGH-1: Нет SSRF-защиты для callback_url

**Файл:** `b2b_api/schemas/check.py:68`

```python
callback_url: Optional[str] = Field(
    None,
    description="URL для webhook уведомления о завершении проверки"
)
```

Клиент может указать `callback_url` как внутренний адрес (например, `http://169.254.169.254/`
для metadata сервиса AWS). Когда webhook будет реализован, это станет SSRF-уязвимостью.

**Решение:** Валидация URL — только HTTPS, запрет приватных IP-диапазонов (RFC 1918),
запрет localhost, metadata endpoints.

---

### HIGH-2: Нет биллинговой логики для B2B

**Файл:** `b2b_api/migrations/b2b_tables.sql:219`

Таблица `b2b_billing_summary` создана, но:
- Нет кода для генерации invoice
- Нет интеграции с платежной системой для B2B
- `checks_today` / `checks_this_month` сбрасываются в коде, но нет scheduled job
- Нет overage billing (сверхквотное использование)

**Решение:** Реализовать billing service: ежемесячные сводки, invoice, интеграция с
платежным шлюзом (Stripe/Tinkoff для юрлиц), email-уведомления.

---

### HIGH-3: Нет клиентского self-service

Создание B2B-клиентов и API-ключей возможно **только через прямой доступ к БД**.
Нет ни API для регистрации клиентов, ни админ-панели.

**Решение:**
- Admin API для создания/управления клиентами (с admin scope)
- Или web-портал для self-service регистрации
- API endpoint для ротации ключей

---

### HIGH-4: CORS настроен небезопасно для production

**Файл:** `b2b_api/app.py:122-138`

```python
allow_origins=["*"] if DEBUG else [
    "https://*.example.com",  # Замените на реальные домены клиентов
],
```

- В DEBUG-режиме: `allow_origins=["*"]` — полностью открытый CORS
- В production: `https://*.example.com` — placeholder, не настроен

**Решение:** Динамический CORS на основе зарегистрированных доменов клиентов.

---

### HIGH-5: Нет горизонтального масштабирования

- Один процесс FastAPI (uvicorn)
- Один файл SQLite
- In-memory rate limiter / cache
- `BackgroundTasks` для AI-проверок (привязан к процессу)

При нескольких B2B-клиентах с высокой нагрузкой система будет деградировать.

**Решение:**
- PostgreSQL + pgbouncer
- Redis для rate limiting и кэша
- Celery/RQ для фоновых задач (AI evaluation)
- Несколько worker-процессов за nginx/gunicorn

---

### HIGH-6: Счетчики использования не сбрасываются автоматически

**Файл:** `b2b_api/middleware/api_key_auth.py:256-271`

```python
async def increment_usage(self, client_id: str):
    await db.execute("""
        UPDATE b2b_clients
        SET checks_today = checks_today + 1,
            checks_this_month = checks_this_month + 1, ...
    """)
```

`checks_today` и `checks_this_month` инкрементируются, но **нет scheduled job
для их сброса**. Поля `last_daily_reset` и `last_monthly_reset` в БД не используются.

**Решение:** Cron job или scheduled task для ежедневного/ежемесячного сброса счетчиков.

---

### HIGH-7: B2B API и teacher_mode — параллельные миры

Две системы проверки работ с разной архитектурой:

| Аспект | teacher_mode | B2B API |
|--------|-------------|---------|
| Транспорт | Telegram Bot | REST API |
| Авторизация | Telegram user_id | API Key |
| Квоты | `quick_check_quotas` | `b2b_clients.monthly_quota` |
| Задания | task17-25 + custom | task19-25 |
| Подписки | teacher_free/basic/standard/premium | free/trial/basic/standard/premium/enterprise |
| Биллинг | Tinkoff (B2C) | Не реализован |

При B2B-распространении учитель из школы-клиента может использовать и бот, и API.
Нет единого учета квот и подписок.

---

## 7. Средние проблемы

### MED-1: Отсутствие structured logging

Все логи — простые строки через `logging.getLogger()`. Для production B2B нужен
JSON-формат с correlation ID для трассировки запросов.

---

### MED-2: White-label branding неполный

`core/branding.py` поддерживает кастомизацию через env-переменные, но:
- Нет привязки branding к B2B-клиенту
- Нет таблицы `schools.branding` (упоминается в комментариях, но не создана)
- B2B API не возвращает branding данные клиенту

---

### MED-3: API не поддерживает task17, task18, full_exam

B2B API ограничен заданиями 19-25:
```python
task_number: int = Field(..., ge=19, le=25)
```

Но teacher_mode поддерживает task17, task18 и проверку полных вариантов.
B2B-клиентам может потребоваться полный функционал.

---

### MED-4: Нет idempotency для создания проверок

`POST /api/v1/check` не поддерживает idempotency key.
Повторный POST с теми же данными создаст дубликат проверки.

---

### MED-5: Health check не проверяет зависимости

```python
@app.get("/health")
async def health_check():
    return {"status": "healthy"}  # Всегда healthy!
```

Не проверяется доступность БД и AI-сервиса.

---

### MED-6: Динамическое создание таблиц

`variant_check_service.py:17`:
```python
async def ensure_tables():
    await db.execute("CREATE TABLE IF NOT EXISTS variant_checks ...")
```

Таблица создается при первом вызове вместо миграций.
Для B2B это антипаттерн — все DDL должны быть через миграции.

---

## 8. Рекомендации по приоритетам

### Фаза 1: Блокеры (необходимо для MVP B2B) — 4-6 недель

| # | Задача | Приоритет | Трудоемкость |
|---|--------|-----------|-------------|
| 1 | Миграция на PostgreSQL | CRIT | 2-3 недели |
| 2 | Реализовать Row-Level Security | CRIT | 1 неделя |
| 3 | Redis для rate limiting + кэша | CRIT | 3-5 дней |
| 4 | Тесты B2B API (unit + integration) | CRIT | 1-2 недели |
| 5 | Убрать callback_url или реализовать webhook | CRIT | 3-5 дней |
| 6 | Admin API для создания клиентов/ключей | HIGH | 3-5 дней |
| 7 | Scheduled job для сброса счетчиков | HIGH | 1-2 дня |

### Фаза 2: Важные улучшения — 3-4 недели

| # | Задача | Приоритет | Трудоемкость |
|---|--------|-----------|-------------|
| 8 | Биллинг B2B (invoice, overage) | HIGH | 2 недели |
| 9 | SSRF-защита для callback_url | HIGH | 1-2 дня |
| 10 | CORS — динамическая настройка | HIGH | 2-3 дня |
| 11 | Celery/RQ для фоновых AI-задач | HIGH | 1 неделя |
| 12 | Structured logging + correlation ID | MED | 3-5 дней |
| 13 | Health check с проверкой зависимостей | MED | 1 день |
| 14 | Поддержка task17/18 в B2B API | MED | 2-3 дня |

### Фаза 3: Полноценный B2B-продукт — 4-6 недель

| # | Задача | Приоритет | Трудоемкость |
|---|--------|-----------|-------------|
| 15 | Клиентский портал (self-service) | MED | 2-3 недели |
| 16 | Webhook delivery с HMAC + retry | MED | 1 неделя |
| 17 | SLA-документация | MED | 3-5 дней |
| 18 | Idempotency keys | MED | 2-3 дня |
| 19 | Monitoring (Prometheus + Grafana) | MED | 1 неделя |
| 20 | Единая система квот teacher_mode + B2B | MED | 1-2 недели |
| 21 | White-label branding привязка к клиенту | LOW | 1 неделя |
| 22 | Проверка вариантов целиком через API | LOW | 1-2 недели |

---

## Заключение

Функциональное ядро — AI-проверка заданий ЕГЭ и модуль учителя — **работает хорошо**
и покрывает все типы заданий (17-25). Код качественный, хорошо структурирован,
с правильной обработкой ошибок и валидацией ввода.

Однако **инфраструктурный слой** (БД, масштабирование, изоляция данных, биллинг, тесты)
**не готов** для B2B-распространения. Основные блокеры:

1. **SQLite** → нужен PostgreSQL
2. **Нет изоляции данных** → нужен RLS или schema-per-tenant
3. **In-memory state** → нужен Redis
4. **Нет тестов B2B** → нужно полное покрытие
5. **Webhook не реализован** → нужно реализовать или убрать

Рекомендуемый путь: **3 фазы по 4-6 недель**, после Фазы 1 можно запускать
ограниченный B2B-пилот с 2-3 школами.
