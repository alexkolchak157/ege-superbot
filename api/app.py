"""
Главное FastAPI приложение для WebApp учителя.

Backend API обеспечивает:
- Аутентификацию через Telegram WebApp initData
- Управление профилем учителя
- Работу с учениками
- Создание и управление заданиями
- Доступ к вопросам и модулям
- Сохранение черновиков

Документация доступна по адресу: /docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import logging

from api.routes import teacher, students, modules, questions, assignments, drafts
from core.config import DEBUG


class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware для обработки заголовков от nginx proxy"""
    async def dispatch(self, request: Request, call_next):
        # Обрабатываем X-Forwarded-Proto для правильной работы Swagger UI через HTTPS
        forwarded_proto = request.headers.get("x-forwarded-proto")
        if forwarded_proto:
            request.scope["scheme"] = forwarded_proto
        return await call_next(request)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO if not DEBUG else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создание FastAPI приложения
app = FastAPI(
    title="Teacher WebApp API",
    version="1.0.0",
    description="Backend API для WebApp режима учителя бота по обществознанию",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Добавляем middleware для обработки заголовков прокси (должен быть первым!)
app.add_middleware(ProxyHeadersMiddleware)

# Настройка CORS
# В продакшене следует ограничить origins только Telegram доменами
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://t.me",
        "https://web.telegram.org",
        "https://telegram.org",
        # Для локальной разработки (убрать в продакшене):
        "http://localhost:*",
        "http://127.0.0.1:*"
    ] if DEBUG else [
        "https://t.me",
        "https://web.telegram.org",
        "https://telegram.org"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# Регистрация роутов
app.include_router(
    teacher.router,
    prefix="/api/teacher",
    tags=["teacher"]
)

app.include_router(
    students.router,
    prefix="/api/teacher",
    tags=["students"]
)

app.include_router(
    modules.router,
    prefix="/api/teacher",
    tags=["modules"]
)

app.include_router(
    questions.router,
    prefix="/api/teacher",
    tags=["questions"]
)

app.include_router(
    assignments.router,
    prefix="/api/teacher",
    tags=["assignments"]
)

app.include_router(
    drafts.router,
    prefix="/api/teacher",
    tags=["drafts"]
)


# Корневой endpoint
@app.get("/", tags=["root"])
async def root():
    """
    Корневой endpoint API.
    Возвращает информацию о статусе API.
    """
    return {
        "message": "Teacher WebApp API is running",
        "version": "1.0.0",
        "status": "healthy",
        "docs": "/docs",
        "redoc": "/redoc"
    }


# Health check endpoint
@app.get("/health", tags=["root"])
async def health_check():
    """
    Health check endpoint для мониторинга.
    Возвращает статус здоровья приложения.
    """
    return {
        "status": "healthy",
        "service": "teacher-webapp-api"
    }


# Обработчик ошибок
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Глобальный обработчик ошибок.
    Логирует ошибки и возвращает читаемый ответ.
    """
    logger.error(f"Необработанная ошибка: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "message": str(exc) if DEBUG else "An error occurred"
        }
    )


# Startup event
@app.on_event("startup")
async def startup_event():
    """
    Выполняется при запуске приложения.
    """
    logger.info("🚀 Teacher WebApp API запущен")
    logger.info(f"Debug режим: {'включен' if DEBUG else 'выключен'}")
    logger.info("📚 Документация доступна на /docs")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """
    Выполняется при остановке приложения.
    """
    logger.info("👋 Teacher WebApp API остановлен")


if __name__ == "__main__":
    import uvicorn

    # Запуск сервера
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=DEBUG,
        log_level="info" if not DEBUG else "debug"
    )
