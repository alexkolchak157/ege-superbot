"""
B2B API - FastAPI приложение для интеграции с онлайн-школами.

Предоставляет:
- POST /api/v1/check - отправка ответа на проверку
- GET /api/v1/check/{id} - получение результата проверки
- GET /api/v1/questions - доступ к банку заданий
- GET /api/v1/me - информация о клиенте
- GET /api/v1/usage - статистика использования

Документация: /docs (Swagger UI), /redoc (ReDoc)
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from starlette.middleware.base import BaseHTTPMiddleware

from b2b_api.routes import check_router, questions_router, client_router
from b2b_api.middleware.rate_limiter import RateLimitMiddleware, get_rate_limiter, RateLimitExceeded
from b2b_api.services.api_logger import APILoggingMiddleware, get_api_logger
from core.config import DEBUG

# Настройка логирования
logging.basicConfig(
    level=logging.INFO if not DEBUG else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager для приложения."""
    # Startup
    logger.info("🚀 B2B API starting up...")

    # Запускаем rate limiter cleanup task
    rate_limiter = get_rate_limiter()
    await rate_limiter.start_cleanup_task()

    # Запускаем API logger
    api_logger = get_api_logger()
    await api_logger.start()

    logger.info("✓ B2B API ready")

    yield

    # Shutdown
    logger.info("👋 B2B API shutting down...")
    await api_logger.stop()
    logger.info("✓ B2B API stopped")


# Создание FastAPI приложения
app = FastAPI(
    title="EGE Superbot B2B API",
    version="1.0.0",
    description="""
## B2B API для интеграции с онлайн-школами

Позволяет автоматически проверять ответы учеников на задания ЕГЭ по обществознанию (19-25).

### Возможности

- **Проверка ответов** - отправляйте ответы учеников и получайте оценки с комментариями
- **Банк заданий** - доступ к базе заданий для тренировки
- **Аналитика** - статистика использования API

### Аутентификация

Используйте API ключ в заголовке `X-API-Key` или как Bearer token:

```
X-API-Key: b2b_live_sk_xxx...
```

или

```
Authorization: Bearer b2b_live_sk_xxx...
```

### Rate Limiting

- Лимиты зависят от вашего тарифа
- Информация о лимитах в заголовках ответа (`X-RateLimit-*`)
- При превышении лимита возвращается статус 429

### Поддержка

Для получения API ключа и вопросов по интеграции: api@example.com
    """,
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
    lifespan=lifespan
)


# Middleware для обработки заголовков прокси
class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        forwarded_proto = request.headers.get("x-forwarded-proto")
        if forwarded_proto:
            request.scope["scheme"] = forwarded_proto
        return await call_next(request)


# Добавляем middleware (порядок важен!)
app.add_middleware(ProxyHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(APILoggingMiddleware, api_prefix="/api/v1")

# CORS настройки
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if DEBUG else [
        "https://*.example.com",  # Замените на реальные домены клиентов
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=[
        "X-RateLimit-Limit-Minute",
        "X-RateLimit-Remaining-Minute",
        "X-RateLimit-Limit-Daily",
        "X-RateLimit-Remaining-Daily",
        "X-RateLimit-Limit-Monthly",
        "X-RateLimit-Remaining-Monthly"
    ]
)


# Регистрация роутов
app.include_router(
    check_router,
    prefix="/api/v1"
)

app.include_router(
    questions_router,
    prefix="/api/v1"
)

app.include_router(
    client_router,
    prefix="/api/v1"
)


# Корневой endpoint
@app.get("/", tags=["root"])
async def root():
    """
    Корневой endpoint API.
    """
    return {
        "service": "EGE Superbot B2B API",
        "version": "1.0.0",
        "status": "healthy",
        "docs": "/docs",
        "redoc": "/redoc"
    }


# Health check
@app.get("/health", tags=["root"])
async def health_check():
    """
    Health check для мониторинга.
    """
    return {
        "status": "healthy",
        "service": "b2b-api"
    }


# Документация Swagger UI
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )


# Документация ReDoc
@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js",
    )


# Обработчик ошибок rate limit
@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content=exc.detail,
        headers={"Retry-After": str(exc.retry_after)}
    )


# Глобальный обработчик ошибок
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": str(exc) if DEBUG else "An internal error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "b2b_api.app:app",
        host="0.0.0.0",
        port=8001,  # Другой порт чем teacher API
        reload=DEBUG,
        log_level="info" if not DEBUG else "debug"
    )
